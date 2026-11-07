//! Plugin → Bridge → (fake) server API → Bridge → plugin, driven tick by tick.

use std::io::Cursor;
use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::extract::{Multipart, Path, State};
use axum::http::{HeaderMap, Request, StatusCode};
use axum::routing::{get, post};
use axum::{Json, Router};
use http_body_util::BodyExt;
use serde_json::{json, Value};
use tower::ServiceExt;

use lrff_bridge_core::config::BridgeConfig;
use lrff_bridge_core::db::Db;
use lrff_bridge_core::{outbox, server, AppState};

const TOKEN: &str = "test-token";

#[derive(Default)]
struct FakeApi {
    fail_next_upload: bool,
    uploads: Vec<Value>,
    jobs: Vec<(Option<String>, Value)>,
}

type Fake = Arc<Mutex<FakeApi>>;

async fn fake_upload(State(fake): State<Fake>, mut form: Multipart) -> (StatusCode, Json<Value>) {
    let mut metadata = Value::Null;
    let mut file_len = 0;
    while let Some(field) = form.next_field().await.unwrap() {
        match field.name() {
            Some("metadata") => {
                metadata = serde_json::from_str(&field.text().await.unwrap()).unwrap()
            }
            Some("file") => file_len = field.bytes().await.unwrap().len(),
            _ => {}
        }
    }
    let mut f = fake.lock().unwrap();
    if std::mem::take(&mut f.fail_next_upload) {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"detail": "busy"})),
        );
    }
    assert!(file_len > 0, "preview must be sent");
    let uuid = metadata["lr_catalog_uuid"].as_str().unwrap().to_string();
    f.uploads.push(metadata);
    (
        StatusCode::OK,
        Json(
            json!({"photo_id": format!("remote-{uuid}"), "s3_key": "k", "already_existed": false}),
        ),
    )
}

async fn fake_job(
    State(fake): State<Fake>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let key = headers
        .get("idempotency-key")
        .map(|v| v.to_str().unwrap().to_string());
    fake.lock().unwrap().jobs.push((key, body));
    (
        StatusCode::ACCEPTED,
        Json(json!({"job_id": "remote-job-1", "status": "queued", "kind": "edit"})),
    )
}

async fn fake_job_state(Path(id): Path<String>) -> Json<Value> {
    Json(json!({"job_id": id, "status": "completed"}))
}

async fn fake_results(State(fake): State<Fake>) -> Json<Value> {
    let f = fake.lock().unwrap();
    let photo_ids = f.jobs[0].1["photo_ids"].as_array().unwrap().clone();
    Json(Value::Array(
        photo_ids
            .iter()
            .map(|id| json!({"job_id": "remote-job-1", "photo_id": id, "lr_settings": {"Exposure2012": 0.35}}))
            .collect(),
    ))
}

async fn spawn_fake_api(fake: Fake) -> String {
    let app = Router::new()
        .route("/health", get(|| async { Json(json!({"status": "ok"})) }))
        .route("/v1/photos", post(fake_upload))
        .route("/v1/jobs/edit", post(fake_job))
        .route("/v1/jobs/{id}", get(fake_job_state))
        .route("/v1/jobs/{id}/result", get(fake_results))
        .with_state(fake);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    format!("http://{addr}")
}

fn state(api: &str, dir: &std::path::Path) -> Arc<AppState> {
    state_with(api, dir, false)
}

fn state_with(api: &str, dir: &std::path::Path, automation: bool) -> Arc<AppState> {
    let config = BridgeConfig {
        port: 0,
        token: TOKEN.into(),
        api_base_url: api.into(),
        automation,
    };
    Arc::new(AppState::new(
        dir.to_path_buf(),
        config,
        Db::open_in_memory().unwrap(),
    ))
}

async fn call(
    state: &Arc<AppState>,
    method: &str,
    uri: &str,
    token: Option<&str>,
    body: Option<Value>,
) -> (StatusCode, Value) {
    let mut req = Request::builder()
        .method(method)
        .uri(uri)
        .header("content-type", "application/json");
    if let Some(t) = token {
        req = req.header("x-lrff-token", t);
    }
    let body = body
        .map(|b| Body::from(b.to_string()))
        .unwrap_or_else(Body::empty);
    let resp = server::router(state.clone())
        .oneshot(req.body(body).unwrap())
        .await
        .unwrap();
    let status = resp.status();
    let bytes = resp.into_body().collect().await.unwrap().to_bytes();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

fn write_jpeg(path: &std::path::Path, w: u32, h: u32) {
    let img = image::RgbImage::from_pixel(w, h, image::Rgb([180, 120, 60]));
    let mut out = Vec::new();
    img.write_to(&mut Cursor::new(&mut out), image::ImageFormat::Jpeg)
        .unwrap();
    std::fs::write(path, out).unwrap();
}

fn photo_body(uuid: &str, path: &std::path::Path) -> Value {
    json!({
        "schema_version": "bridge-photo-v1",
        "lr_catalog_uuid": uuid,
        "file_path": path.display().to_string(),
        "lr_develop_settings": {"Exposure2012": 0.2},
        "lr_metadata": {"rating": 4, "pick_status": 1},
    })
}

#[tokio::test]
async fn edit_job_roundtrip_with_retry() {
    let dir = tempfile::tempdir().unwrap();
    let fake: Fake = Arc::new(Mutex::new(FakeApi {
        fail_next_upload: true,
        ..Default::default()
    }));
    let api = spawn_fake_api(fake.clone()).await;
    let st = state(&api, dir.path());
    let jpg = dir.path().join("IMG_0001.jpg");
    write_jpeg(&jpg, 2000, 1500);

    // Plugin side: auth, validation, registration.
    let (s, _) = call(&st, "GET", "/v1/profiles", None, None).await;
    assert_eq!(s, StatusCode::UNAUTHORIZED);
    let (s, _) = call(&st, "GET", "/health", None, None).await;
    assert_eq!(s, StatusCode::OK);
    let (s, photo) = call(
        &st,
        "POST",
        "/v1/photos",
        Some(TOKEN),
        Some(photo_body("lr-1", &jpg)),
    )
    .await;
    assert_eq!(
        (s, photo["status"].as_str()),
        (StatusCode::ACCEPTED, Some("pending"))
    );

    let profile = "6ba7b810-9dad-11d1-80b4-00c04fd430c8";
    let edit = |uuids: Value| json!({"schema_version": "bridge-edit-v1", "profile_id": profile, "lr_catalog_uuids": uuids});
    let (s, err) = call(
        &st,
        "POST",
        "/v1/jobs/edit",
        Some(TOKEN),
        Some(edit(json!(["lr-unknown"]))),
    )
    .await;
    assert_eq!(s, StatusCode::UNPROCESSABLE_ENTITY);
    assert!(err["error"].as_str().unwrap().contains("lr-unknown"));
    let (s, job) = call(
        &st,
        "POST",
        "/v1/jobs/edit",
        Some(TOKEN),
        Some(edit(json!(["lr-1", "lr-1"]))),
    )
    .await;
    assert_eq!(
        (s, job["status"].as_str()),
        (StatusCode::ACCEPTED, Some("waiting_for_photos"))
    );
    let job_id = job["job_id"].as_str().unwrap().to_string();

    // Server busy → photo stays pending with a retry scheduled; job keeps waiting.
    outbox::tick(&st).await;
    let p = st.db().photo("lr-1").unwrap().unwrap();
    assert_eq!((p.status.as_str(), p.attempts), ("pending", 1));
    assert!(p.last_error.unwrap().contains("503"));

    // Retry → upload + job submit in the same pass.
    st.db().retry_all_now().unwrap();
    outbox::tick(&st).await;
    assert_eq!(st.db().photo("lr-1").unwrap().unwrap().status, "uploaded");
    let (s, job) = call(&st, "GET", &format!("/v1/jobs/{job_id}"), Some(TOKEN), None).await;
    assert_eq!(
        (s, job["status"].as_str(), job["remote_job_id"].as_str()),
        (StatusCode::OK, Some("queued"), Some("remote-job-1"))
    );

    // Poll → completed, results mapped back to catalog UUIDs.
    st.db().retry_all_now().unwrap();
    outbox::tick(&st).await;
    let (_, job) = call(&st, "GET", &format!("/v1/jobs/{job_id}"), Some(TOKEN), None).await;
    assert_eq!(job["status"], "completed");
    assert_eq!(job["profile_id"], profile);
    assert_eq!(
        job["results"],
        json!([{"lr_catalog_uuid": "lr-1", "lr_settings": {"Exposure2012": 0.35}}])
    );

    // What the server received.
    let f = fake.lock().unwrap();
    assert_eq!(f.uploads[0]["schema_version"], "photo-upload-v1");
    assert_eq!(
        f.uploads[0]["lr_develop_settings"],
        json!({"Exposure2012": 0.2})
    );
    assert_eq!(
        f.uploads[0]["lr_metadata"],
        json!({"rating": 4, "pick_status": 1})
    );
    let (key, body) = &f.jobs[0];
    assert_eq!(
        key.as_deref(),
        Some(format!("lrff-bridge-{job_id}").as_str())
    );
    assert_eq!(body["schema_version"], "edit-request-v1");
    assert_eq!(body["photo_ids"], json!(["remote-lr-1"]));
    assert!(body.get("lr_catalog_uuids").is_none() && body.get("collection_name").is_none());
}

#[tokio::test]
async fn unreachable_file_retries_but_broken_file_fails_job() {
    let dir = tempfile::tempdir().unwrap();
    let api = spawn_fake_api(Arc::new(Mutex::new(FakeApi::default()))).await;
    let st = state(&api, dir.path());

    let offline = dir.path().join("unplugged-drive").join("a.cr3");
    let broken = dir.path().join("b.nef");
    std::fs::write(&broken, b"not a raw file").unwrap();
    call(
        &st,
        "POST",
        "/v1/photos",
        Some(TOKEN),
        Some(photo_body("off", &offline)),
    )
    .await;
    call(
        &st,
        "POST",
        "/v1/photos",
        Some(TOKEN),
        Some(photo_body("bad", &broken)),
    )
    .await;
    let train = json!({
        "schema_version": "bridge-train-v1", "profile_name": "Wedding", "genre": "wedding",
        "format_type": "raw", "color_type": "color", "lr_catalog_uuids": ["bad"],
    });
    let (_, job) = call(&st, "POST", "/v1/jobs/train", Some(TOKEN), Some(train)).await;

    outbox::tick(&st).await;
    let off = st.db().photo("off").unwrap().unwrap();
    assert_eq!((off.status.as_str(), off.attempts), ("pending", 1));
    assert_eq!(st.db().photo("bad").unwrap().unwrap().status, "failed");
    let job = st
        .db()
        .job(job["job_id"].as_str().unwrap())
        .unwrap()
        .unwrap();
    assert_eq!(job.status, "failed");
    let reason = job.last_error.unwrap();
    assert!(reason.contains("no usable photo") && reason.contains("photo bad skipped"));
}

#[tokio::test]
async fn automation_is_off_by_default_and_round_trips_when_on() {
    let dir = tempfile::tempdir().unwrap();
    let off = state("http://127.0.0.1:9", dir.path());
    let (s, _) = call(
        &off,
        "POST",
        "/v1/automation/commands",
        Some(TOKEN),
        Some(json!({"command": "ping"})),
    )
    .await;
    assert_eq!(
        s,
        StatusCode::NOT_FOUND,
        "off unless enabled in bridge.json"
    );
    let (s, _) = call(&off, "GET", "/v1/automation/next", Some(TOKEN), None).await;
    assert_eq!(s, StatusCode::NOT_FOUND);

    let on = state_with("http://127.0.0.1:9", dir.path(), true);
    let (s, _) = call(&on, "GET", "/v1/automation/next", None, None).await;
    assert_eq!(s, StatusCode::UNAUTHORIZED, "token required");
    let (s, err) = call(
        &on,
        "POST",
        "/v1/automation/commands",
        Some(TOKEN),
        Some(json!({"command": "eval"})),
    )
    .await;
    assert_eq!(
        s,
        StatusCode::UNPROCESSABLE_ENTITY,
        "only known commands: {err}"
    );

    let (s, cmd) = call(
        &on,
        "POST",
        "/v1/automation/commands",
        Some(TOKEN),
        Some(json!({"command": "list_photos", "args": {"limit": 3}})),
    )
    .await;
    assert_eq!(s, StatusCode::ACCEPTED);
    let id = cmd["id"].as_u64().unwrap();
    // the plugin picks it up …
    let (s, next) = call(&on, "GET", "/v1/automation/next", Some(TOKEN), None).await;
    assert_eq!(
        (s, next["command"].as_str()),
        (StatusCode::OK, Some("list_photos"))
    );
    let (s, _) = call(&on, "GET", "/v1/automation/next", Some(TOKEN), None).await;
    assert_eq!(s, StatusCode::NO_CONTENT);
    // … and reports back
    let (s, _) = call(
        &on,
        "POST",
        &format!("/v1/automation/commands/{id}/result"),
        Some(TOKEN),
        Some(json!({"ok": true, "result": {"photos": []}})),
    )
    .await;
    assert_eq!(s, StatusCode::OK);
    let (_, done) = call(
        &on,
        "GET",
        &format!("/v1/automation/commands/{id}"),
        Some(TOKEN),
        None,
    )
    .await;
    assert_eq!(
        (done["status"].as_str(), done["ok"].as_bool()),
        (Some("done"), Some(true))
    );
    let (_, status) = call(&on, "GET", "/v1/automation/status", Some(TOKEN), None).await;
    assert_eq!(status["enabled"], json!(true));
}

#[tokio::test]
async fn job_goes_on_without_offline_and_broken_photos() {
    let dir = tempfile::tempdir().unwrap();
    let fake: Fake = Arc::new(Mutex::new(FakeApi::default()));
    let api = spawn_fake_api(fake.clone()).await;
    let st = state(&api, dir.path());

    let good = dir.path().join("good.jpg");
    write_jpeg(&good, 2000, 1500);
    let broken = dir.path().join("broken.nef");
    std::fs::write(&broken, b"not a raw file").unwrap();
    let offline = dir.path().join("offline-onedrive").join("a.raf");
    for (uuid, path) in [("good", &good), ("bad", &broken), ("off", &offline)] {
        call(
            &st,
            "POST",
            "/v1/photos",
            Some(TOKEN),
            Some(photo_body(uuid, path)),
        )
        .await;
    }
    let edit = json!({"schema_version": "bridge-edit-v1",
        "profile_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "lr_catalog_uuids": ["good", "bad", "off"]});
    let (_, job) = call(&st, "POST", "/v1/jobs/edit", Some(TOKEN), Some(edit)).await;
    let job_id = job["job_id"].as_str().unwrap().to_string();

    // The offline file is retried a few times; meanwhile the job waits.
    outbox::tick(&st).await;
    assert_eq!(
        st.db().job(&job_id).unwrap().unwrap().status,
        "waiting_for_photos"
    );
    for _ in 0..5 {
        st.db().retry_all_now().unwrap();
        outbox::tick(&st).await;
    }

    // Then it runs with the one usable photo; the offline one stays pending.
    let job = st.db().job(&job_id).unwrap().unwrap();
    assert_eq!(job.status, "completed");
    assert_eq!(
        fake.lock().unwrap().jobs[0].1["photo_ids"],
        json!(["remote-good"])
    );
    assert_eq!(st.db().photo("off").unwrap().unwrap().status, "pending");
}
