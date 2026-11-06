//! Background loop: turns outbox rows into server API calls.
//!
//! 1. Pending photos → build preview → `POST /v1/photos`.
//! 2. Jobs waiting for photos → once all are uploaded, `POST /v1/jobs/{kind}` with a
//!    stable `Idempotency-Key` (safe to resend after a crash).
//! 3. Queued/running jobs → poll `GET /v1/jobs/{id}`; on completion fetch edit results
//!    and map server photo ids back to Lightroom catalog UUIDs.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use serde_json::{json, Value};

use crate::api_client::ApiError;
use crate::db::JobRow;
use crate::preview::{build_preview, PreviewError};
use crate::AppState;

const PHOTO_BATCH: usize = 4;
const JOB_BATCH: usize = 20;
/// Seconds between status polls of a queued/running server job.
pub const POLL_SECS: i64 = 2;

pub async fn run(state: Arc<AppState>) {
    loop {
        tick(&state).await;
        tokio::time::sleep(Duration::from_secs(1)).await;
    }
}

/// One pass over everything that is due. Errors are logged, never fatal.
pub async fn tick(state: &AppState) {
    if let Err(e) = upload_photos(state).await {
        tracing::warn!("photo upload pass failed: {e:#}");
    }
    if let Err(e) = advance_jobs(state).await {
        tracing::warn!("job pass failed: {e:#}");
    }
}

async fn upload_photos(state: &AppState) -> Result<()> {
    let due = state.db().due_photos(PHOTO_BATCH)?;
    for photo in due {
        let uuid = photo.lr_catalog_uuid.clone();
        let path = PathBuf::from(&photo.file_path);
        let jpeg = match tokio::task::spawn_blocking(move || build_preview(&path)).await? {
            Ok(jpeg) => jpeg,
            // File not reachable (external drive unplugged, NAS offline): try again later.
            Err(e @ PreviewError::Read { .. }) => {
                state.db().retry_photo_later(&uuid, &e.to_string())?;
                continue;
            }
            Err(e) => {
                tracing::warn!(%uuid, "no usable preview: {e}");
                state.db().mark_photo_failed(&uuid, &e.to_string())?;
                continue;
            }
        };
        let metadata = json!({
            "schema_version": "photo-upload-v1",
            "lr_catalog_uuid": uuid,
            "exif_snapshot": photo.exif_snapshot,
            "lr_develop_settings": photo.lr_develop_settings,
        });
        match state.api.upload_photo(jpeg, &metadata).await {
            Ok(created) => {
                tracing::info!(%uuid, remote = %created.photo_id, "photo uploaded");
                state.db().mark_photo_uploaded(&uuid, &created.photo_id)?;
            }
            Err(ApiError::Transient(msg)) => state.db().retry_photo_later(&uuid, &msg)?,
            Err(ApiError::Permanent(msg)) => state.db().mark_photo_failed(&uuid, &msg)?,
        }
    }
    Ok(())
}

async fn advance_jobs(state: &AppState) -> Result<()> {
    let due = state.db().due_jobs(JOB_BATCH)?;
    for job in due {
        match job.status.as_str() {
            "waiting_for_photos" => submit_when_ready(state, &job).await?,
            _ => poll(state, &job).await?,
        }
    }
    Ok(())
}

/// Server photo ids per catalog UUID, or the reason the job cannot run (yet).
enum PhotoReadiness {
    Ready(Vec<String>),
    Waiting,
    Failed(String),
}

fn photo_readiness(state: &AppState, job: &JobRow) -> Result<PhotoReadiness> {
    let db = state.db();
    let mut ids = Vec::with_capacity(job.lr_catalog_uuids.len());
    let mut waiting = false;
    for uuid in &job.lr_catalog_uuids {
        match db.photo(uuid)? {
            None => {
                return Ok(PhotoReadiness::Failed(format!(
                    "photo {uuid} is not registered"
                )))
            }
            Some(p) if p.status == "failed" => {
                let reason = p.last_error.unwrap_or_default();
                return Ok(PhotoReadiness::Failed(format!(
                    "photo {uuid} failed: {reason}"
                )));
            }
            Some(p) => match p.remote_photo_id {
                Some(id) if p.status == "uploaded" => ids.push(id),
                _ => waiting = true,
            },
        }
    }
    Ok(if waiting {
        PhotoReadiness::Waiting
    } else {
        PhotoReadiness::Ready(ids)
    })
}

/// Bridge request → server request: same fields, catalog UUIDs swapped for photo ids.
fn server_body(job: &JobRow, photo_ids: Vec<String>) -> Value {
    let mut body = job.request.as_object().cloned().unwrap_or_default();
    body.remove("lr_catalog_uuids");
    body.retain(|_, v| !v.is_null());
    let schema = if job.kind == "train" {
        "train-request-v1"
    } else {
        "edit-request-v1"
    };
    body.insert("schema_version".into(), json!(schema));
    body.insert("photo_ids".into(), json!(photo_ids));
    Value::Object(body)
}

async fn submit_when_ready(state: &AppState, job: &JobRow) -> Result<()> {
    let photo_ids = match photo_readiness(state, job)? {
        PhotoReadiness::Ready(ids) => ids,
        PhotoReadiness::Waiting => {
            state.db().update_job(&job.job_id, &job.status, None, 1)?;
            return Ok(());
        }
        PhotoReadiness::Failed(reason) => {
            state.db().fail_job(&job.job_id, &reason)?;
            return Ok(());
        }
    };
    let body = server_body(job, photo_ids);
    match state
        .api
        .create_job(&job.kind, &body, &job.idempotency_key)
        .await
    {
        Ok(accepted) => {
            tracing::info!(job = %job.job_id, remote = %accepted.job_id, "job submitted");
            state
                .db()
                .update_job(&job.job_id, "queued", Some(&accepted.job_id), POLL_SECS)?;
        }
        Err(ApiError::Transient(msg)) => state.db().retry_job_later(&job.job_id, &msg)?,
        Err(ApiError::Permanent(msg)) => state.db().fail_job(&job.job_id, &msg)?,
    }
    Ok(())
}

async fn poll(state: &AppState, job: &JobRow) -> Result<()> {
    let Some(remote) = job.remote_job_id.as_deref() else {
        state
            .db()
            .fail_job(&job.job_id, "queued without server job id")?;
        return Ok(());
    };
    let snapshot = match state.api.get_job(remote).await {
        Ok(s) => s,
        Err(ApiError::Transient(msg)) => return state.db().retry_job_later(&job.job_id, &msg),
        Err(ApiError::Permanent(msg)) => return state.db().fail_job(&job.job_id, &msg),
    };
    match snapshot.status.as_str() {
        "completed" if job.kind == "edit" => match state.api.get_results(remote).await {
            Ok(results) => {
                let mapped = map_results(state, job, results)?;
                state.db().complete_job(&job.job_id, Some(&mapped))?;
            }
            Err(ApiError::Transient(msg)) => state.db().retry_job_later(&job.job_id, &msg)?,
            Err(ApiError::Permanent(msg)) => state.db().fail_job(&job.job_id, &msg)?,
        },
        "completed" => state.db().complete_job(&job.job_id, None)?,
        "failed" => state.db().fail_job(&job.job_id, "server job failed")?,
        other => state.db().update_job(&job.job_id, other, None, POLL_SECS)?,
    }
    Ok(())
}

fn map_results(
    state: &AppState,
    job: &JobRow,
    results: Vec<crate::api_client::EditResult>,
) -> Result<Value> {
    let db = state.db();
    let mut by_remote: HashMap<String, String> = HashMap::new();
    for uuid in &job.lr_catalog_uuids {
        if let Some(remote) = db.photo(uuid)?.and_then(|p| p.remote_photo_id) {
            by_remote.insert(remote, uuid.clone());
        }
    }
    let mapped: Vec<Value> = results
        .into_iter()
        .filter_map(|r| {
            let uuid = by_remote.get(&r.photo_id)?;
            Some(json!({ "lr_catalog_uuid": uuid, "lr_settings": r.lr_settings }))
        })
        .collect();
    Ok(Value::Array(mapped))
}
