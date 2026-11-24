//! Local API for the Lightroom plugin (`packages/contracts/openapi/plugin-bridge-api.yaml`).

// Validation helpers return a ready `Response` as error; boxing it buys nothing here.
#![allow(clippy::result_large_err)]

use std::collections::BTreeSet;
use std::sync::Arc;

use axum::extract::{Path, Request, State};
use axum::http::StatusCode;
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::de::DeserializeOwned;
use serde::Deserialize;
use serde_json::{json, Map, Value};

use crate::AppState;

pub const TOKEN_HEADER: &str = "x-calotype-token";
/// Header names before the rename (ADR 006), still accepted.
pub const OLD_TOKEN_HEADERS: [&str; 2] = ["x-tarsier-token", "x-lrff-token"];

type Shared = Arc<AppState>;

pub fn router(state: Shared) -> Router {
    let v1 = Router::new()
        .route("/v1/photos", post(register_photo))
        .route("/v1/photos/{uuid}", get(photo_state))
        .route("/v1/jobs/train", post(queue_train))
        .route("/v1/jobs/edit", post(queue_edit))
        .route("/v1/jobs/cull", post(queue_cull))
        .route("/v1/jobs/{job_id}", get(job_state))
        .route("/v1/profiles", get(profiles))
        .route("/v1/automation/status", get(automation_status))
        .route("/v1/automation/commands", post(automation_enqueue))
        .route("/v1/automation/commands/{id}", get(automation_get))
        .route(
            "/v1/automation/commands/{id}/result",
            post(automation_result),
        )
        .route("/v1/automation/next", get(automation_next))
        .route_layer(middleware::from_fn_with_state(state.clone(), require_token));
    Router::new()
        .route("/health", get(health))
        .merge(v1)
        .with_state(state)
}

fn error(status: StatusCode, msg: impl Into<String>) -> Response {
    (status, Json(json!({ "error": msg.into() }))).into_response()
}

fn internal(e: anyhow::Error) -> Response {
    tracing::error!("internal error: {e:#}");
    error(
        StatusCode::INTERNAL_SERVER_ERROR,
        "internal error, see bridge log",
    )
}

/// Parse with our own error body instead of axum's plain-text rejection.
fn parse<T: DeserializeOwned>(body: Value) -> Result<T, Response> {
    serde_json::from_value(body).map_err(|e| error(StatusCode::UNPROCESSABLE_ENTITY, e.to_string()))
}

fn expect_schema(actual: &str, expected: &str) -> Result<(), Response> {
    if actual == expected {
        Ok(())
    } else {
        Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("schema_version must be '{expected}'"),
        ))
    }
}

/// Constant-time comparison so the token cannot be guessed byte by byte.
fn token_matches(given: &str, expected: &str) -> bool {
    given.len() == expected.len()
        && given
            .bytes()
            .zip(expected.bytes())
            .fold(0u8, |acc, (a, b)| acc | (a ^ b))
            == 0
}

async fn require_token(State(state): State<Shared>, req: Request, next: Next) -> Response {
    let ok = req
        .headers()
        .get(TOKEN_HEADER)
        .or_else(|| OLD_TOKEN_HEADERS.iter().find_map(|h| req.headers().get(*h)))
        .and_then(|v| v.to_str().ok())
        .is_some_and(|t| token_matches(t, &state.token()));
    if !ok {
        return error(
            StatusCode::UNAUTHORIZED,
            "missing or wrong X-Calotype-Token",
        );
    }
    next.run(req).await
}

async fn health() -> Json<Value> {
    Json(json!({ "status": "ok", "version": env!("CARGO_PKG_VERSION") }))
}

/// A photo registration. The Bridge builds the upload itself (preview, measured light), so it
/// types what it acts on; every other top-level field is kept with the photo and forwarded
/// into the upload metadata unchanged (null ones left out) — a newer plugin's field reaches
/// the server without a Bridge change, and the server, a tolerant reader, decides about it.
/// `file_path` stays local; the typed fields win over a forwarded one of the same name.
#[derive(Deserialize)]
struct PhotoReq {
    schema_version: String,
    lr_catalog_uuid: String,
    file_path: String,
    #[serde(default)]
    exif_snapshot: Map<String, Value>,
    #[serde(default)]
    lr_develop_settings: Map<String, Value>,
    /// Rating, pick/reject flag, color label (culling labels).
    #[serde(default)]
    lr_metadata: Map<String, Value>,
    #[serde(flatten)]
    extra: Map<String, Value>,
}

async fn register_photo(State(state): State<Shared>, Json(body): Json<Value>) -> Response {
    let req: PhotoReq = match parse(body) {
        Ok(r) => r,
        Err(resp) => return resp,
    };
    if let Err(resp) = expect_schema(&req.schema_version, "bridge-photo-v1") {
        return resp;
    }
    if req.lr_catalog_uuid.trim().is_empty() || req.file_path.trim().is_empty() {
        return error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "lr_catalog_uuid and file_path are required",
        );
    }
    let mut extra = req.extra;
    extra.retain(|_, v| !v.is_null());
    let row = state.db().upsert_photo(
        &req.lr_catalog_uuid,
        &req.file_path,
        &Value::Object(req.exif_snapshot),
        &Value::Object(req.lr_develop_settings),
        &Value::Object(req.lr_metadata),
        &Value::Object(extra),
    );
    match row {
        Ok(row) => (StatusCode::ACCEPTED, Json(row)).into_response(),
        Err(e) => internal(e),
    }
}

async fn photo_state(State(state): State<Shared>, Path(uuid): Path<String>) -> Response {
    match state.db().photo(&uuid) {
        Ok(Some(row)) => Json(row).into_response(),
        Ok(None) => error(StatusCode::NOT_FOUND, "unknown photo"),
        Err(e) => internal(e),
    }
}

/// A train or edit request from the plugin. The Bridge reads only what it acts on — the
/// schema and the photos, which it swaps for server photo ids — and forwards every other field
/// (profile, options, look …) to the server unchanged: a new server field needs no Bridge
/// change, and the server alone validates them (`calotype_queue.payloads`; its 422 becomes the
/// job's error). Tolerant reader: unknown fields are not rejected here.
#[derive(Deserialize)]
struct JobReq {
    schema_version: String,
    lr_catalog_uuids: Vec<String>,
    #[serde(flatten)]
    rest: Map<String, Value>,
}

/// Deduplicate, keep order, and require every photo to be registered first.
fn checked_uuids(state: &AppState, uuids: Vec<String>) -> Result<Vec<String>, Response> {
    let mut seen = BTreeSet::new();
    let uuids: Vec<String> = uuids
        .into_iter()
        .filter(|u| seen.insert(u.clone()))
        .collect();
    if uuids.is_empty() {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "lr_catalog_uuids must not be empty",
        ));
    }
    let db = state.db();
    let mut unknown = Vec::new();
    for u in &uuids {
        match db.photo(u) {
            Ok(Some(_)) => {}
            Ok(None) => unknown.push(u.clone()),
            Err(e) => return Err(internal(e)),
        }
    }
    if !unknown.is_empty() {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("register these photos first via POST /v1/photos: {unknown:?}"),
        ));
    }
    Ok(uuids)
}

fn accept_job(state: &AppState, kind: &str, request: Value, uuids: &[String]) -> Response {
    match state.db().insert_job(kind, &request, uuids) {
        Ok(row) => (StatusCode::ACCEPTED, Json(row)).into_response(),
        Err(e) => internal(e),
    }
}

/// Check the schema and the photos, then store the request for the outbox.
fn queue_job(state: &AppState, kind: &str, schema: &str, body: Value) -> Response {
    let req: JobReq = match parse(body) {
        Ok(r) => r,
        Err(resp) => return resp,
    };
    if let Err(resp) = expect_schema(&req.schema_version, schema) {
        return resp;
    }
    let uuids = match checked_uuids(state, req.lr_catalog_uuids) {
        Ok(u) => u,
        Err(resp) => return resp,
    };
    accept_job(state, kind, Value::Object(req.rest), &uuids)
}

async fn queue_train(State(state): State<Shared>, Json(body): Json<Value>) -> Response {
    queue_job(&state, "train", "bridge-train-v1", body)
}

async fn queue_edit(State(state): State<Shared>, Json(body): Json<Value>) -> Response {
    queue_job(&state, "edit", "bridge-edit-v1", body)
}

/// Like [`JobReq`], plus the catalog the Bridge reads Lightroom's culling scores from (not
/// forwarded: the scores reach the server with the photos).
#[derive(Deserialize)]
struct CullReq {
    schema_version: String,
    /// The open catalog (`catalog:getPath()`): Lightroom's assisted-culling scores are read
    /// from it and become culling features.
    #[serde(default)]
    catalog_path: Option<String>,
    lr_catalog_uuids: Vec<String>,
    #[serde(flatten)]
    rest: Map<String, Value>,
}

async fn queue_cull(State(state): State<Shared>, Json(body): Json<Value>) -> Response {
    let req: CullReq = match parse(body) {
        Ok(r) => r,
        Err(resp) => return resp,
    };
    if let Err(resp) = expect_schema(&req.schema_version, "bridge-cull-v1") {
        return resp;
    }
    let uuids = match checked_uuids(&state, req.lr_catalog_uuids) {
        Ok(u) => u,
        Err(resp) => return resp,
    };
    if let Some(path) = req.catalog_path.filter(|p| !p.trim().is_empty()) {
        let wanted = uuids.clone();
        let read = tokio::task::spawn_blocking(move || {
            crate::catalog::culling_scores(std::path::Path::new(&path), &wanted)
        })
        .await;
        match read {
            Ok(Ok(scores)) => {
                tracing::info!(
                    scored = scores.len(),
                    photos = uuids.len(),
                    "Lightroom culling scores"
                );
                let db = state.db();
                for (uuid, s) in &scores {
                    if let Err(e) = db.set_culling_scores(uuid, s) {
                        return internal(e);
                    }
                }
            }
            // Without the scores culling still works on its own features.
            Ok(Err(e)) => tracing::warn!("cannot read Lightroom culling scores: {e:#}"),
            Err(e) => tracing::warn!("cannot read Lightroom culling scores: {e}"),
        }
    }
    accept_job(&state, "cull", Value::Object(req.rest), &uuids)
}

async fn job_state(State(state): State<Shared>, Path(job_id): Path<String>) -> Response {
    match state.db().job(&job_id) {
        Ok(Some(row)) => Json(row).into_response(),
        Ok(None) => error(StatusCode::NOT_FOUND, "unknown job"),
        Err(e) => internal(e),
    }
}

async fn profiles(State(state): State<Shared>) -> Response {
    match state.api.list_profiles().await {
        Ok(v) => Json(v).into_response(),
        Err(e) => error(StatusCode::BAD_GATEWAY, format!("server API: {e}")),
    }
}

// ---- automation (opt-in end-to-end test channel, see automation.rs) -------------

fn automation_off() -> Response {
    error(
        StatusCode::NOT_FOUND,
        "automation is off (set \"automation\": true in bridge.json)",
    )
}

async fn automation_status(State(state): State<Shared>) -> Response {
    let enabled = state.config().automation;
    Json(json!({
        "enabled": enabled,
        "plugin_idle_secs": state.automation.plugin_idle_secs(),
        "commands": crate::automation::COMMANDS,
    }))
    .into_response()
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EnqueueReq {
    command: String,
    #[serde(default)]
    args: Value,
}

async fn automation_enqueue(State(state): State<Shared>, Json(body): Json<Value>) -> Response {
    if !state.config().automation {
        return automation_off();
    }
    let req: EnqueueReq = match parse(body) {
        Ok(r) => r,
        Err(resp) => return resp,
    };
    match state.automation.enqueue(&req.command, req.args) {
        Ok(cmd) => (StatusCode::ACCEPTED, Json(cmd)).into_response(),
        Err(msg) => error(StatusCode::UNPROCESSABLE_ENTITY, msg),
    }
}

async fn automation_next(State(state): State<Shared>) -> Response {
    if !state.config().automation {
        return automation_off();
    }
    match state.automation.next() {
        Some(cmd) => Json(cmd).into_response(),
        None => StatusCode::NO_CONTENT.into_response(),
    }
}

async fn automation_get(State(state): State<Shared>, Path(id): Path<u64>) -> Response {
    if !state.config().automation {
        return automation_off();
    }
    match state.automation.get(id) {
        Some(cmd) => Json(cmd).into_response(),
        None => error(StatusCode::NOT_FOUND, "unknown command"),
    }
}

#[derive(Deserialize)]
struct ResultReq {
    ok: bool,
    #[serde(default)]
    result: Value,
}

async fn automation_result(
    State(state): State<Shared>,
    Path(id): Path<u64>,
    Json(body): Json<Value>,
) -> Response {
    if !state.config().automation {
        return automation_off();
    }
    let req: ResultReq = match parse(body) {
        Ok(r) => r,
        Err(resp) => return resp,
    };
    match state.automation.finish(id, req.ok, req.result) {
        Some(cmd) => Json(cmd).into_response(),
        None => error(StatusCode::NOT_FOUND, "unknown command"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn token_comparison() {
        assert!(token_matches("abc", "abc"));
        assert!(!token_matches("abd", "abc"));
        assert!(!token_matches("ab", "abc"));
    }
}
