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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
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
    let row = state.db().upsert_photo(
        &req.lr_catalog_uuid,
        &req.file_path,
        &Value::Object(req.exif_snapshot),
        &Value::Object(req.lr_develop_settings),
        &Value::Object(req.lr_metadata),
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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrainReq {
    schema_version: String,
    #[serde(default)]
    correlation_id: Option<String>,
    profile_name: String,
    genre: String,
    format_type: String,
    color_type: String,
    lr_catalog_uuids: Vec<String>,
    #[serde(default)]
    base_preset: Option<Map<String, Value>>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EditReq {
    schema_version: String,
    #[serde(default)]
    correlation_id: Option<String>,
    profile_id: uuid::Uuid,
    #[serde(default)]
    collection_name: Option<String>,
    #[serde(default)]
    straighten: bool,
    lr_catalog_uuids: Vec<String>,
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

async fn queue_train(State(state): State<Shared>, Json(body): Json<Value>) -> Response {
    let req: TrainReq = match parse(body) {
        Ok(r) => r,
        Err(resp) => return resp,
    };
    if let Err(resp) = expect_schema(&req.schema_version, "bridge-train-v1") {
        return resp;
    }
    if !["raw", "jpeg_tiff"].contains(&req.format_type.as_str()) {
        return error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "format_type must be 'raw' or 'jpeg_tiff'",
        );
    }
    if !["color", "bw"].contains(&req.color_type.as_str()) {
        return error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "color_type must be 'color' or 'bw'",
        );
    }
    let uuids = match checked_uuids(&state, req.lr_catalog_uuids) {
        Ok(u) => u,
        Err(resp) => return resp,
    };
    let request = json!({
        "correlation_id": req.correlation_id,
        "profile_name": req.profile_name,
        "genre": req.genre,
        "format_type": req.format_type,
        "color_type": req.color_type,
        "base_preset": req.base_preset,
    });
    accept_job(&state, "train", request, &uuids)
}

async fn queue_edit(State(state): State<Shared>, Json(body): Json<Value>) -> Response {
    let req: EditReq = match parse(body) {
        Ok(r) => r,
        Err(resp) => return resp,
    };
    if let Err(resp) = expect_schema(&req.schema_version, "bridge-edit-v1") {
        return resp;
    }
    let uuids = match checked_uuids(&state, req.lr_catalog_uuids) {
        Ok(u) => u,
        Err(resp) => return resp,
    };
    let request = json!({
        "correlation_id": req.correlation_id,
        "profile_id": req.profile_id.to_string(),
        "collection_name": req.collection_name,
        "straighten": req.straighten,
    });
    accept_job(&state, "edit", request, &uuids)
}

#[derive(Deserialize)]
struct CullReq {
    schema_version: String,
    #[serde(default)]
    correlation_id: Option<String>,
    lr_catalog_uuids: Vec<String>,
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
    let request = json!({ "correlation_id": req.correlation_id });
    accept_job(&state, "cull", request, &uuids)
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
