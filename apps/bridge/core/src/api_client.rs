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
}

#[derive(Debug, Deserialize)]
pub struct EditResult {
    pub photo_id: String,
    pub lr_settings: Value,
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
}

fn normalize(url: &str) -> String {
    url.trim().trim_end_matches('/').to_string()
}
