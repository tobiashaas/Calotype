//! HTTP client for the server API (`packages/contracts/openapi/bridge-api.yaml`).

use std::sync::RwLock;
use std::time::Duration;

use reqwest::{multipart, Client, Response, StatusCode};
use serde::Deserialize;
use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ApiError {
    /// Worth retrying later: network down, timeout, 408/429/5xx.
    #[error("temporary: {0}")]
    Transient(String),
    /// Retrying will not help: the server rejected the request.
    #[error("rejected: {0}")]
    Permanent(String),
}

impl From<reqwest::Error> for ApiError {
    fn from(e: reqwest::Error) -> Self {
        match e.status() {
            Some(s) if !is_transient(s) => ApiError::Permanent(e.to_string()),
            _ => ApiError::Transient(e.to_string()),
        }
    }
}

fn is_transient(status: StatusCode) -> bool {
    status == StatusCode::REQUEST_TIMEOUT
        || status == StatusCode::TOO_MANY_REQUESTS
        || status.is_server_error()
}

async fn check(resp: Response) -> Result<Response, ApiError> {
    let status = resp.status();
    if status.is_success() {
        return Ok(resp);
    }
    let body = resp.text().await.unwrap_or_default();
    let msg = format!(
        "HTTP {status}: {}",
        body.chars().take(500).collect::<String>()
    );
    Err(if is_transient(status) {
        ApiError::Transient(msg)
    } else {
        ApiError::Permanent(msg)
    })
}

#[derive(Debug, Deserialize)]
pub struct PhotoCreated {
    pub photo_id: String,
}

#[derive(Debug, Deserialize)]
pub struct JobAccepted {
    pub job_id: String,
    #[serde(default)]
    pub profile_id: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct JobSnapshot {
    pub status: String,
    #[serde(default)]
    pub profile_id: Option<String>,
    #[serde(default)]
    pub failure_reason: Option<String>,
    /// Why it failed as a code (`no_examples` …); older servers send none.
    #[serde(default)]
    pub failure_code: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct EditResult {
    pub photo_id: String,
    pub lr_settings: Value,
    /// Learned mask strengths: AI masks to add with these local values (older servers: none).
    #[serde(default)]
    pub retouch: Option<Value>,
    /// Straightened, but the photo keeps its own crop (no crop keys in `lr_settings`).
    #[serde(default)]
    pub kept_crop: Option<bool>,
}

pub struct ApiClient {
    http: Client,
    base_url: RwLock<String>,
}

impl ApiClient {
    pub fn new(base_url: &str) -> Self {
        let http = Client::builder()
            .timeout(Duration::from_secs(60))
            .connect_timeout(Duration::from_secs(5))
            .user_agent(concat!("calotype-bridge/", env!("CARGO_PKG_VERSION")))
            .build()
            .expect("static client config is valid");
        Self {
            http,
            base_url: RwLock::new(normalize(base_url)),
        }
    }

    pub fn base_url(&self) -> String {
        self.base_url.read().expect("lock").clone()
    }

    pub fn set_base_url(&self, url: &str) {
        *self.base_url.write().expect("lock") = normalize(url);
    }

    fn url(&self, path: &str) -> String {
        format!("{}{path}", self.base_url())
    }

    pub async fn health(&self) -> bool {
        match self
            .http
            .get(self.url("/health"))
            .timeout(Duration::from_secs(3))
            .send()
            .await
        {
            Ok(r) => r.status().is_success(),
            Err(_) => false,
        }
    }

    pub async fn upload_photo(
        &self,
        jpeg: Vec<u8>,
        metadata: &Value,
    ) -> Result<PhotoCreated, ApiError> {
        let file = multipart::Part::bytes(jpeg)
            .file_name("preview.jpg")
            .mime_str("image/jpeg")
            .expect("static mime");
        let form = multipart::Form::new()
            .part("file", file)
            .text("metadata", metadata.to_string());
        let resp = self
            .http
            .post(self.url("/v1/photos"))
            .multipart(form)
            .send()
            .await?;
        Ok(check(resp).await?.json().await?)
    }

    pub async fn create_job(
        &self,
        kind: &str,
        body: &Value,
        idempotency_key: &str,
    ) -> Result<JobAccepted, ApiError> {
        let resp = self
            .http
            .post(self.url(&format!("/v1/jobs/{kind}")))
            .header("Idempotency-Key", idempotency_key)
            .json(body)
            .send()
            .await?;
        Ok(check(resp).await?.json().await?)
    }

    pub async fn get_job(&self, job_id: &str) -> Result<JobSnapshot, ApiError> {
        let resp = self
            .http
            .get(self.url(&format!("/v1/jobs/{job_id}")))
            .send()
            .await?;
        Ok(check(resp).await?.json().await?)
    }

    pub async fn get_results(&self, job_id: &str) -> Result<Vec<EditResult>, ApiError> {
        let resp = self
            .http
            .get(self.url(&format!("/v1/jobs/{job_id}/result")))
            .send()
            .await?;
        Ok(check(resp).await?.json().await?)
    }

    /// Culling decisions of a completed cull job (photo_id, bucket, score, reason, method).
    pub async fn get_cull_results(&self, job_id: &str) -> Result<Vec<Value>, ApiError> {
        let resp = self
            .http
            .get(self.url(&format!("/v1/jobs/{job_id}/cull-result")))
            .send()
            .await?;
        Ok(check(resp).await?.json().await?)
    }

    pub async fn list_profiles(&self) -> Result<Value, ApiError> {
        let resp = self.http.get(self.url("/v1/profiles")).send().await?;
        Ok(check(resp).await?.json().await?)
    }

    /// Rename a profile and/or change its marker (`profile-update-v1`, sent as it is).
    pub async fn update_profile(
        &self,
        profile_id: &str,
        body: &Value,
    ) -> Result<ServerAnswer, reqwest::Error> {
        let resp = self
            .http
            .patch(self.url(&format!("/v1/profiles/{profile_id}")))
            .json(body)
            .send()
            .await?;
        ServerAnswer::read(resp).await
    }

    /// Soft-delete a profile (the server only hides it).
    pub async fn delete_profile(&self, profile_id: &str) -> Result<ServerAnswer, reqwest::Error> {
        let resp = self
            .http
            .delete(self.url(&format!("/v1/profiles/{profile_id}")))
            .send()
            .await?;
        ServerAnswer::read(resp).await
    }
}

/// A server answer the Bridge hands to the plugin as it is: its status (404 unknown profile,
/// 422 invalid body …) means something to the plugin, unlike for the outbox's jobs.
#[derive(Debug)]
pub struct ServerAnswer {
    pub status: StatusCode,
    /// The JSON body; `Null` when there is none (204) or it is not JSON.
    pub body: Value,
}

impl ServerAnswer {
    async fn read(resp: Response) -> Result<Self, reqwest::Error> {
        let status = resp.status();
        let bytes = resp.bytes().await?;
        let body = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
        Ok(Self { status, body })
    }
}

fn normalize(url: &str) -> String {
    url.trim().trim_end_matches('/').to_string()
}
