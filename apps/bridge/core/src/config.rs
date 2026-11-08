//! `bridge.json`: port, access token and server API address.
//!
//! The plugin reads the same file to find the Bridge, so it lives in a fixed,
//! per-user data directory.

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

pub const DEFAULT_PORT: u16 = 47600;
pub const DEFAULT_API_BASE_URL: &str = "http://127.0.0.1:8080";
pub const CONFIG_FILE: &str = "bridge.json";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BridgeConfig {
    pub port: u16,
    pub token: String,
    pub api_base_url: String,
    /// Automation channel for end-to-end tests in Lightroom (see automation.rs). Off unless
    /// set to true by hand; missing in older files means off.
    #[serde(default)]
    pub automation: bool,
    /// Install the project's looks and retouch presets for Lightroom / Camera Raw on start.
    #[serde(default = "default_true")]
    pub install_presets: bool,
}

impl BridgeConfig {
    fn generate() -> Self {
        Self {
            port: DEFAULT_PORT,
            token: new_token(),
            api_base_url: DEFAULT_API_BASE_URL.to_string(),
            automation: false,
            install_presets: true,
        }
    }
}

/// 256 bits of randomness, hex-encoded.
fn new_token() -> String {
    format!(
        "{}{}",
        uuid::Uuid::new_v4().simple(),
        uuid::Uuid::new_v4().simple()
    )
}

/// `LRFF_BRIDGE_DATA_DIR`, else `%APPDATA%\LRFrameFlow` / `~/Library/Application Support/LRFrameFlow`.
pub fn default_data_dir() -> Result<PathBuf> {
    if let Some(dir) = std::env::var_os("LRFF_BRIDGE_DATA_DIR") {
        return Ok(PathBuf::from(dir));
    }
    let base = dirs::data_dir().context("no per-user data directory on this system")?;
    Ok(base.join("LRFrameFlow"))
}

/// Load `bridge.json`, creating it with a fresh token on first start.
pub fn load_or_create(data_dir: &Path) -> Result<BridgeConfig> {
    fs::create_dir_all(data_dir)
        .with_context(|| format!("cannot create data dir {}", data_dir.display()))?;
    let path = data_dir.join(CONFIG_FILE);
    if path.exists() {
        let raw =
            fs::read_to_string(&path).with_context(|| format!("cannot read {}", path.display()))?;
        return serde_json::from_str(&raw)
            .with_context(|| format!("invalid {} — fix or delete it", path.display()));
    }
    let config = BridgeConfig::generate();
    save(data_dir, &config)?;
    Ok(config)
}

pub fn save(data_dir: &Path, config: &BridgeConfig) -> Result<()> {
    let path = data_dir.join(CONFIG_FILE);
    let tmp = data_dir.join(format!("{CONFIG_FILE}.tmp"));
    fs::write(&tmp, serde_json::to_string_pretty(config)?)?;
    fs::rename(&tmp, &path).with_context(|| format!("cannot write {}", path.display()))?;
    Ok(())
}

fn default_true() -> bool {
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn creates_config_once_and_reuses_token() {
        let dir = tempfile::tempdir().unwrap();
        let first = load_or_create(dir.path()).unwrap();
        assert_eq!(first.port, DEFAULT_PORT);
        assert_eq!(first.token.len(), 64);
        let second = load_or_create(dir.path()).unwrap();
        assert_eq!(first, second);
    }
}
