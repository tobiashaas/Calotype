//! LR-FrameFlow Bridge desktop app: starts the Bridge core and shows its status.

// No console window in release builds on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use lrff_bridge_core::{Bridge, StatusSnapshot};
use tauri::{Manager, State};

struct BridgeHandle(Bridge);

#[tauri::command]
async fn bridge_status(bridge: State<'_, BridgeHandle>) -> Result<StatusSnapshot, String> {
    bridge.0.state.status().await.map_err(|e| format!("{e:#}"))
}

#[tauri::command]
fn set_api_base_url(bridge: State<'_, BridgeHandle>, url: String) -> Result<(), String> {
    bridge
        .0
        .state
        .set_api_base_url(&url)
        .map_err(|e| format!("{e:#}"))
}

#[tauri::command]
fn retry_now(bridge: State<'_, BridgeHandle>) -> Result<(), String> {
    bridge
        .0
        .state
        .db()
        .retry_all_now()
        .map_err(|e| format!("{e:#}"))
}

fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .init();

    tauri::Builder::default()
        .setup(|app| {
            let data_dir = lrff_bridge_core::config::default_data_dir()?;
            let bridge = tauri::async_runtime::block_on(lrff_bridge_core::start(data_dir))?;
            app.manage(BridgeHandle(bridge));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            bridge_status,
            set_api_base_url,
            retry_now
        ])
        .run(tauri::generate_context!())
        .expect("error while running the LR-FrameFlow Bridge");
}
