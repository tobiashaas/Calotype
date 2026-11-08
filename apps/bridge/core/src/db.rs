//! SQLite outbox: everything the plugin asks for is stored here first, then sent to
//! the server API by the background loop in [`crate::outbox`].

use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::Result;
use rusqlite::{params, Connection, OptionalExtension, Row};
use serde::Serialize;
use serde_json::Value;

const SCHEMA_VERSION: i64 = 3;

pub fn now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or_default()
}

/// Retry delay after `attempts` failures: 2, 4, 8 … capped at 5 minutes.
pub fn backoff_secs(attempts: i64) -> i64 {
    2_i64.saturating_pow(attempts.clamp(1, 16) as u32).min(300)
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct PhotoRow {
    pub lr_catalog_uuid: String,
    #[serde(skip)]
    pub file_path: String,
    #[serde(skip)]
    pub exif_snapshot: Value,
    #[serde(skip)]
    pub lr_develop_settings: Value,
    /// Rating, pick/reject flag, color label (culling labels).
    #[serde(skip)]
    pub lr_metadata: Value,
    pub status: String,
    pub remote_photo_id: Option<String>,
    pub attempts: i64,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct JobRow {
    pub job_id: String,
    pub kind: String,
    #[serde(skip)]
    pub request: Value,
    #[serde(skip)]
    pub lr_catalog_uuids: Vec<String>,
    #[serde(skip)]
    pub idempotency_key: String,
    pub status: String,
    pub remote_job_id: Option<String>,
    pub attempts: i64,
    pub last_error: Option<String>,
    /// Server profile: created by a train job, applied by an edit job.
    pub profile_id: Option<String>,
    pub results: Option<Value>,
}

pub struct Db {
    conn: Connection,
}

fn json(text: String) -> Value {
    serde_json::from_str(&text).unwrap_or(Value::Null)
}

fn photo_from_row(r: &Row) -> rusqlite::Result<PhotoRow> {
    Ok(PhotoRow {
        lr_catalog_uuid: r.get(0)?,
        file_path: r.get(1)?,
        exif_snapshot: json(r.get(2)?),
        lr_develop_settings: json(r.get(3)?),
        status: r.get(4)?,
        remote_photo_id: r.get(5)?,
        attempts: r.get(6)?,
        last_error: r.get(7)?,
        lr_metadata: json(r.get(8)?),
    })
}

fn job_from_row(r: &Row) -> rusqlite::Result<JobRow> {
    let results: Option<String> = r.get(9)?;
    Ok(JobRow {
        job_id: r.get(0)?,
        kind: r.get(1)?,
        request: json(r.get(2)?),
        lr_catalog_uuids: serde_json::from_str(&r.get::<_, String>(3)?).unwrap_or_default(),
        idempotency_key: r.get(4)?,
        status: r.get(5)?,
        remote_job_id: r.get(6)?,
        attempts: r.get(7)?,
        last_error: r.get(8)?,
        profile_id: r.get(10)?,
        results: results.map(json),
    })
}

const PHOTO_COLS: &str = "lr_catalog_uuid, file_path, exif_json, settings_json, status, \
                          remote_photo_id, attempts, last_error, metadata_json";
const JOB_COLS: &str = "job_id, kind, request_json, uuids_json, idempotency_key, status, \
                        remote_job_id, attempts, last_error, results_json, profile_id";

impl Db {
    pub fn open(path: &Path) -> Result<Self> {
        Self::init(Connection::open(path)?)
    }

    pub fn open_in_memory() -> Result<Self> {
        Self::init(Connection::open_in_memory()?)
    }

    fn init(conn: Connection) -> Result<Self> {
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "busy_timeout", 5000)?;
        let version: i64 = conn.pragma_query_value(None, "user_version", |r| r.get(0))?;
        if version < 1 {
            conn.execute_batch(
                "CREATE TABLE photos (
                    lr_catalog_uuid TEXT PRIMARY KEY,
                    file_path       TEXT NOT NULL,
                    exif_json       TEXT NOT NULL,
                    settings_json   TEXT NOT NULL,
                    status          TEXT NOT NULL,   -- pending | uploaded | failed
                    remote_photo_id TEXT,
                    attempts        INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at INTEGER NOT NULL DEFAULT 0,
                    last_error      TEXT,
                    created_at      INTEGER NOT NULL,
                    updated_at      INTEGER NOT NULL
                );
                CREATE TABLE jobs (
                    job_id          TEXT PRIMARY KEY,
                    kind            TEXT NOT NULL,   -- train | edit
                    request_json    TEXT NOT NULL,
                    uuids_json      TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    status          TEXT NOT NULL,   -- waiting_for_photos | queued | running | completed | failed
                    remote_job_id   TEXT,
                    attempts        INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at INTEGER NOT NULL DEFAULT 0,
                    last_error      TEXT,
                    results_json    TEXT,
                    created_at      INTEGER NOT NULL,
                    updated_at      INTEGER NOT NULL
                );
                CREATE INDEX photos_due ON photos(status, next_attempt_at);
                CREATE INDEX jobs_due ON jobs(status, next_attempt_at);",
            )?;
        }
        if version < 2 {
            conn.execute_batch("ALTER TABLE jobs ADD COLUMN profile_id TEXT;")?;
        }
        if version < 3 {
            conn.execute_batch(
                "ALTER TABLE photos ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';",
            )?;
        }
        if version < SCHEMA_VERSION {
            conn.pragma_update(None, "user_version", SCHEMA_VERSION)?;
        }
        Ok(Self { conn })
    }

    // ---- photos -------------------------------------------------------------

    /// Insert, or refresh a known photo. An uploaded photo is sent again only when its
    /// settings, EXIF or decisions (rating, flag, label) changed — re-edits and re-ratings
    /// must reach the server, unchanged re-registrations cost nothing.
    pub fn upsert_photo(
        &self,
        uuid: &str,
        file_path: &str,
        exif: &Value,
        settings: &Value,
        metadata: &Value,
    ) -> Result<PhotoRow> {
        if let Some(existing) = self.photo(uuid)? {
            let unchanged = existing.exif_snapshot == *exif
                && existing.lr_develop_settings == *settings
                && existing.lr_metadata == *metadata;
            if existing.status == "uploaded" && unchanged {
                return Ok(existing);
            }
        }
        let t = now();
        self.conn.execute(
            "INSERT INTO photos (lr_catalog_uuid, file_path, exif_json, settings_json,
                                 metadata_json, status, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, 'pending', ?6, ?6)
             ON CONFLICT(lr_catalog_uuid) DO UPDATE SET
                 file_path = excluded.file_path,
                 exif_json = excluded.exif_json,
                 settings_json = excluded.settings_json,
                 metadata_json = excluded.metadata_json,
                 status = 'pending',
                 attempts = 0,
                 next_attempt_at = 0,
                 last_error = NULL,
                 updated_at = excluded.updated_at",
            params![
                uuid,
                file_path,
                exif.to_string(),
                settings.to_string(),
                metadata.to_string(),
                t
            ],
        )?;
        Ok(self.photo(uuid)?.expect("row exists after upsert"))
    }

    pub fn photo(&self, uuid: &str) -> Result<Option<PhotoRow>> {
        Ok(self
            .conn
            .query_row(
                &format!("SELECT {PHOTO_COLS} FROM photos WHERE lr_catalog_uuid = ?1"),
                [uuid],
                photo_from_row,
            )
            .optional()?)
    }

    pub fn due_photos(&self, limit: usize) -> Result<Vec<PhotoRow>> {
        let mut stmt = self.conn.prepare(&format!(
            "SELECT {PHOTO_COLS} FROM photos
             WHERE status = 'pending' AND next_attempt_at <= ?1
             ORDER BY created_at LIMIT ?2"
        ))?;
        let rows = stmt.query_map(params![now(), limit as i64], photo_from_row)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    pub fn mark_photo_uploaded(&self, uuid: &str, remote_id: &str) -> Result<()> {
        self.conn.execute(
            "UPDATE photos SET status = 'uploaded', remote_photo_id = ?2, last_error = NULL,
                               updated_at = ?3 WHERE lr_catalog_uuid = ?1",
            params![uuid, remote_id, now()],
        )?;
        Ok(())
    }

    pub fn mark_photo_failed(&self, uuid: &str, error: &str) -> Result<()> {
        self.conn.execute(
            "UPDATE photos SET status = 'failed', attempts = attempts + 1, last_error = ?2,
                               updated_at = ?3 WHERE lr_catalog_uuid = ?1",
            params![uuid, error, now()],
        )?;
        Ok(())
    }

    pub fn retry_photo_later(&self, uuid: &str, error: &str) -> Result<()> {
        let attempts: i64 = self.conn.query_row(
            "SELECT attempts + 1 FROM photos WHERE lr_catalog_uuid = ?1",
            [uuid],
            |r| r.get(0),
        )?;
        self.conn.execute(
            "UPDATE photos SET attempts = ?2, next_attempt_at = ?3, last_error = ?4,
                               updated_at = ?5 WHERE lr_catalog_uuid = ?1",
            params![uuid, attempts, now() + backoff_secs(attempts), error, now()],
        )?;
        Ok(())
    }

    // ---- jobs ---------------------------------------------------------------

    pub fn insert_job(&self, kind: &str, request: &Value, uuids: &[String]) -> Result<JobRow> {
        let job_id = uuid::Uuid::new_v4().to_string();
        let t = now();
        self.conn.execute(
            "INSERT INTO jobs (job_id, kind, request_json, uuids_json, idempotency_key, status,
                               created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, 'waiting_for_photos', ?6, ?6)",
            params![
                job_id,
                kind,
                request.to_string(),
                serde_json::to_string(uuids)?,
                format!("calotype-bridge-{job_id}"),
                t
            ],
        )?;
        Ok(self.job(&job_id)?.expect("row exists after insert"))
    }

    pub fn job(&self, job_id: &str) -> Result<Option<JobRow>> {
        Ok(self
            .conn
            .query_row(
                &format!("SELECT {JOB_COLS} FROM jobs WHERE job_id = ?1"),
                [job_id],
                job_from_row,
            )
            .optional()?)
    }

    /// Jobs waiting for photos, or queued/running jobs whose next poll is due.
    pub fn due_jobs(&self, limit: usize) -> Result<Vec<JobRow>> {
        let mut stmt = self.conn.prepare(&format!(
            "SELECT {JOB_COLS} FROM jobs
             WHERE status IN ('waiting_for_photos', 'queued', 'running') AND next_attempt_at <= ?1
             ORDER BY created_at LIMIT ?2"
        ))?;
        let rows = stmt.query_map(params![now(), limit as i64], job_from_row)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// Set status (and remote id) and schedule the next check in `delay` seconds.
    pub fn update_job(
        &self,
        job_id: &str,
        status: &str,
        remote_job_id: Option<&str>,
        delay: i64,
    ) -> Result<()> {
        self.conn.execute(
            "UPDATE jobs SET status = ?2, remote_job_id = COALESCE(?3, remote_job_id),
                             next_attempt_at = ?4, updated_at = ?5 WHERE job_id = ?1",
            params![job_id, status, remote_job_id, now() + delay, now()],
        )?;
        Ok(())
    }

    pub fn set_job_profile(&self, job_id: &str, profile_id: &str) -> Result<()> {
        self.conn.execute(
            "UPDATE jobs SET profile_id = ?2, updated_at = ?3 WHERE job_id = ?1",
            params![job_id, profile_id, now()],
        )?;
        Ok(())
    }

    pub fn complete_job(&self, job_id: &str, results: Option<&Value>) -> Result<()> {
        self.conn.execute(
            "UPDATE jobs SET status = 'completed', results_json = ?2, last_error = NULL,
                             updated_at = ?3 WHERE job_id = ?1",
            params![job_id, results.map(Value::to_string), now()],
        )?;
        Ok(())
    }

    pub fn fail_job(&self, job_id: &str, error: &str) -> Result<()> {
        self.conn.execute(
            "UPDATE jobs SET status = 'failed', last_error = ?2, updated_at = ?3 WHERE job_id = ?1",
            params![job_id, error, now()],
        )?;
        Ok(())
    }

    pub fn retry_job_later(&self, job_id: &str, error: &str) -> Result<()> {
        let attempts: i64 = self.conn.query_row(
            "SELECT attempts + 1 FROM jobs WHERE job_id = ?1",
            [job_id],
            |r| r.get(0),
        )?;
        self.conn.execute(
            "UPDATE jobs SET attempts = ?2, next_attempt_at = ?3, last_error = ?4,
                             updated_at = ?5 WHERE job_id = ?1",
            params![
                job_id,
                attempts,
                now() + backoff_secs(attempts),
                error,
                now()
            ],
        )?;
        Ok(())
    }

    // ---- status for the UI --------------------------------------------------

    /// "Retry now": make every waiting photo and active job due immediately
    /// (e.g. after plugging the external drive back in).
    pub fn retry_all_now(&self) -> Result<()> {
        self.conn.execute_batch(
            "UPDATE photos SET next_attempt_at = 0 WHERE status = 'pending';
             UPDATE jobs SET next_attempt_at = 0
                 WHERE status IN ('waiting_for_photos', 'queued', 'running');",
        )?;
        Ok(())
    }

    pub fn counts(&self, table: &str) -> Result<Vec<(String, i64)>> {
        let table = match table {
            "photos" => "photos",
            _ => "jobs",
        };
        let mut stmt = self.conn.prepare(&format!(
            "SELECT status, COUNT(*) FROM {table} GROUP BY status ORDER BY 1"
        ))?;
        let rows = stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn upsert_resends_uploaded_photo_only_when_something_changed() {
        let db = Db::open_in_memory().unwrap();
        let s1 = json!({"Exposure2012": 0.1});
        let m1 = json!({"rating": 3});
        db.upsert_photo("u1", "a.cr3", &json!({}), &s1, &m1)
            .unwrap();
        let p = db
            .upsert_photo("u1", "b.cr3", &json!({}), &s1, &m1)
            .unwrap();
        assert_eq!(p.file_path, "b.cr3", "pending photo takes the new path");

        db.mark_photo_uploaded("u1", "remote-1").unwrap();
        let same = db
            .upsert_photo("u1", "c.cr3", &json!({}), &s1, &m1)
            .unwrap();
        assert_eq!(
            (same.status.as_str(), same.file_path.as_str()),
            ("uploaded", "b.cr3")
        );

        let rerated = db
            .upsert_photo("u1", "b.cr3", &json!({}), &s1, &json!({"rating": 5}))
            .unwrap();
        assert_eq!(rerated.status, "pending", "new rating goes to the server");
        assert_eq!(rerated.remote_photo_id.as_deref(), Some("remote-1"));
        assert_eq!(rerated.lr_metadata, json!({"rating": 5}));
    }

    #[test]
    fn retry_pushes_photo_out_of_due_list() {
        let db = Db::open_in_memory().unwrap();
        db.upsert_photo("u1", "a.cr3", &json!({}), &json!({}), &json!({}))
            .unwrap();
        assert_eq!(db.due_photos(10).unwrap().len(), 1);
        db.retry_photo_later("u1", "offline").unwrap();
        assert!(db.due_photos(10).unwrap().is_empty());
        let p = db.photo("u1").unwrap().unwrap();
        assert_eq!((p.attempts, p.last_error.as_deref()), (1, Some("offline")));
    }

    #[test]
    fn backoff_grows_and_caps() {
        assert_eq!(backoff_secs(1), 2);
        assert_eq!(backoff_secs(3), 8);
        assert_eq!(backoff_secs(50), 300);
    }

    #[test]
    fn migrates_v1_database() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("old.sqlite3");
        {
            let conn = Connection::open(&path).unwrap();
            conn.execute_batch(
                "CREATE TABLE photos (lr_catalog_uuid TEXT PRIMARY KEY, file_path TEXT NOT NULL,
                    exif_json TEXT NOT NULL, settings_json TEXT NOT NULL, status TEXT NOT NULL,
                    remote_photo_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at INTEGER NOT NULL DEFAULT 0, last_error TEXT,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
                 CREATE TABLE jobs (job_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    request_json TEXT NOT NULL, uuids_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, status TEXT NOT NULL, remote_job_id TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT, results_json TEXT, created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL);
                 PRAGMA user_version = 1;",
            )
            .unwrap();
        }
        let db = Db::open(&path).unwrap();
        let photo = db
            .upsert_photo("p", "a.cr3", &json!({}), &json!({}), &json!({"rating": 2}))
            .unwrap();
        assert_eq!(photo.lr_metadata, json!({"rating": 2}), "v3 column exists");
        let job = db.insert_job("train", &json!({}), &["u".into()]).unwrap();
        db.set_job_profile(&job.job_id, "p-1").unwrap();
        assert_eq!(
            db.job(&job.job_id).unwrap().unwrap().profile_id.as_deref(),
            Some("p-1")
        );
        drop(db);
        Db::open(&path).unwrap(); // reopening an up-to-date DB is a no-op
    }

    #[test]
    fn job_lifecycle() {
        let db = Db::open_in_memory().unwrap();
        let job = db
            .insert_job("edit", &json!({"profile_id": "p"}), &["u1".into()])
            .unwrap();
        assert_eq!(job.status, "waiting_for_photos");
        assert!(job.idempotency_key.ends_with(&job.job_id));
        db.update_job(&job.job_id, "queued", Some("r1"), 0).unwrap();
        db.complete_job(&job.job_id, Some(&json!([1]))).unwrap();
        let job = db.job(&job.job_id).unwrap().unwrap();
        assert_eq!(
            (job.status.as_str(), job.remote_job_id.as_deref()),
            ("completed", Some("r1"))
        );
        assert_eq!(job.results, Some(json!([1])));
        assert_eq!(
            db.counts("jobs").unwrap(),
            vec![("completed".to_string(), 1)]
        );
    }
}
