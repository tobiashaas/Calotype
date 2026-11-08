//! Tarsier Bridge core (ADR 004).
//!
//! Runs a local HTTP API for the Lightroom plugin on `127.0.0.1`, keeps every request
//! in a SQLite outbox and forwards it to the server API in the background. Usable
//! headless (`tarsier-bridge-headless`) or embedded in the Tauri app.

pub mod api_client;
pub mod automation;
pub mod config;
pub mod db;
pub mod folder;
pub mod outbox;
pub mod presets;
pub mod preview;
pub mod server;
pub mod xmp;

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard, RwLock};

use anyhow::{Context, Result};
use serde::Serialize;
use tokio::task::JoinHandle;

use api_client::ApiClient;
use config::BridgeConfig;
use db::Db;

pub const DB_FILE: &str = "bridge.sqlite3";

pub struct AppState {
    pub data_dir: PathBuf,
    pub api: ApiClient,
    config: RwLock<BridgeConfig>,
    db: Mutex<Db>,
    pub automation: automation::AutomationQueue,
}

#[derive(Debug, Serialize)]
pub struct StatusSnapshot {
    pub version: &'static str,
    pub port: u16,
    pub api_base_url: String,
    pub api_reachable: bool,
    pub data_dir: String,
    pub photos: Vec<(String, i64)>,
    pub jobs: Vec<(String, i64)>,
}

impl AppState {
    pub fn new(data_dir: PathBuf, config: BridgeConfig, db: Db) -> Self {
        Self {
            api: ApiClient::new(&config.api_base_url),
            data_dir,
            config: RwLock::new(config),
            db: Mutex::new(db),
            automation: automation::AutomationQueue::default(),
        }
    }

    /// Short-lived DB access; never hold the guard across an `.await`.
    pub fn db(&self) -> MutexGuard<'_, Db> {
        self.db
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    pub fn token(&self) -> String {
        self.config.read().expect("config lock").token.clone()
    }

    pub fn config(&self) -> BridgeConfig {
        self.config.read().expect("config lock").clone()
    }

    /// Change the server API address and persist it to `bridge.json`.
    pub fn set_api_base_url(&self, url: &str) -> Result<()> {
        let url = url.trim();
        anyhow::ensure!(
            url.starts_with("http://") || url.starts_with("https://"),
            "API address must start with http:// or https://"
        );
        let mut cfg = self.config.write().expect("config lock");
        cfg.api_base_url = url.trim_end_matches('/').to_string();
        config::save(&self.data_dir, &cfg)?;
        self.api.set_base_url(&cfg.api_base_url);
        Ok(())
    }

    pub async fn status(&self) -> Result<StatusSnapshot> {
        let (photos, jobs) = {
            let db = self.db();
            (db.counts("photos")?, db.counts("jobs")?)
        };
        let cfg = self.config();
        Ok(StatusSnapshot {
            version: env!("CARGO_PKG_VERSION"),
            port: cfg.port,
            api_base_url: cfg.api_base_url,
            api_reachable: self.api.health().await,
            data_dir: self.data_dir.display().to_string(),
            photos,
            jobs,
        })
    }
}

/// A running Bridge: HTTP server + outbox loop. Dropping it stops both.
pub struct Bridge {
    pub state: Arc<AppState>,
    pub addr: SocketAddr,
    tasks: Vec<JoinHandle<()>>,
}

impl Drop for Bridge {
    fn drop(&mut self) {
        for t in &self.tasks {
            t.abort();
        }
    }
}

/// Load config + DB from `data_dir` and start on the configured port.
pub async fn start(data_dir: PathBuf) -> Result<Bridge> {
    let config = config::load_or_create(&data_dir)?;
    if config.install_presets {
        match presets::camera_raw_settings_dir().map(|dir| presets::install(&dir)) {
            Some(Ok(0)) => {}
            Some(Ok(n)) => {
                tracing::info!("installed {n} Tarsier presets — restart Lightroom to see them")
            }
            Some(Err(e)) => tracing::warn!("presets not installed: {e:#}"),
            None => tracing::warn!("presets not installed: no Camera Raw settings folder"),
        }
    }
    let db = Db::open(&data_dir.join(DB_FILE))?;
    let port = config.port;
    start_with(Arc::new(AppState::new(data_dir, config, db)), port).await
}

/// Start with prepared state. `port = 0` picks a free port (tests).
pub async fn start_with(state: Arc<AppState>, port: u16) -> Result<Bridge> {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", port))
        .await
        .with_context(|| {
            format!("port {port} on 127.0.0.1 is in use — is another Bridge running?")
        })?;
    let addr = listener.local_addr()?;
    let app = server::router(state.clone());
    let server = tokio::spawn(async move {
        if let Err(e) = axum::serve(listener, app).await {
            tracing::error!("bridge server stopped: {e}");
        }
    });
    let outbox = tokio::spawn(outbox::run(state.clone()));
    tracing::info!(%addr, "bridge listening");
    Ok(Bridge {
        state,
        addr,
        tasks: vec![server, outbox],
    })
}
