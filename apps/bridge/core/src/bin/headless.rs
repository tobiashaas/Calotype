//! Bridge without window — for development, servers and CI.

use anyhow::Result;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let data_dir = lrff_bridge_core::config::default_data_dir()?;
    let bridge = lrff_bridge_core::start(data_dir.clone()).await?;
    let cfg = bridge.state.config();
    println!(
        "LR-FrameFlow Bridge {} on http://{}",
        env!("CARGO_PKG_VERSION"),
        bridge.addr
    );
    println!(
        "config: {}",
        data_dir
            .join(lrff_bridge_core::config::CONFIG_FILE)
            .display()
    );
    println!("server API: {}", cfg.api_base_url);

    tokio::signal::ctrl_c().await?;
    println!("stopping");
    Ok(())
}
