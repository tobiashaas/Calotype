//! Folder mode without Lightroom. Talks to the running Bridge like the plugin does.
//!
//!     lrff-folder train  <DIR> --name "Business Warm" [--genre business] [--color color]
//!     lrff-folder apply  <DIR> --profile "Business Warm" [--force] [--out <DIR>]
//!     lrff-folder profiles
//!
//! train: edited RAWs (RAW + XMP with develop settings) are the training material.
//! apply: unedited RAWs get a new XMP sidecar; import the folder into Lightroom afterwards.
//! train --style <preset.xmp>: a Lightroom preset as the profile's style layer — the model
//!              predicts exposure/white balance/tone per photo, the preset adds the look.
//! --files-from <list>: only these files (one name or path per line), e.g. a train/test split.
//! --out <dir>: write sidecars there instead of next to the RAWs (read-only cards,
//!              evaluation against existing edits). The source folder is never touched.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use serde_json::{json, Map, Value};

use lrff_bridge_core::config::{self, BridgeConfig};
use lrff_bridge_core::folder::{self, FolderPhoto};
use lrff_bridge_core::xmp;

#[derive(Parser)]
#[command(
    name = "lrff-folder",
    version,
    about = "LR-FrameFlow folder mode (RAW + XMP, no Lightroom)"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Train a profile from edited RAWs (those with an XMP sidecar holding develop settings).
    Train {
        dir: PathBuf,
        #[arg(long)]
        name: String,
        #[arg(long, default_value = "other")]
        genre: String,
        #[arg(long, default_value = "color", value_parser = ["color", "bw"])]
        color: String,
        /// Only use the files listed here (one file name or path per line).
        #[arg(long)]
        files_from: Option<PathBuf>,
        /// Lightroom preset (.xmp) whose look is layered on every prediction.
        #[arg(long)]
        style: Option<PathBuf>,
    },
    /// Apply a profile to the RAWs in a folder and write XMP sidecars.
    Apply {
        dir: PathBuf,
        /// Profile id or exact name.
        #[arg(long)]
        profile: String,
        /// Also overwrite develop settings in sidecars that are already edited.
        #[arg(long)]
        force: bool,
        /// Only use the files listed here (one file name or path per line).
        #[arg(long)]
        files_from: Option<PathBuf>,
        /// Write the sidecars into this folder instead of next to the RAWs.
        #[arg(long)]
        out: Option<PathBuf>,
    },
    /// List profiles on the server.
    Profiles,
}

struct Bridge {
    http: reqwest::Client,
    base: String,
    token: String,
}

impl Bridge {
    fn connect() -> Result<Self> {
        let path = config::default_data_dir()?.join(config::CONFIG_FILE);
        let raw = std::fs::read_to_string(&path).with_context(|| {
            format!(
                "no Bridge settings at {} — start the Bridge first",
                path.display()
            )
        })?;
        let cfg: BridgeConfig = serde_json::from_str(&raw)?;
        Ok(Self {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(30))
                .build()?,
            base: format!("http://127.0.0.1:{}", cfg.port),
            token: cfg.token,
        })
    }

    async fn call(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<&Value>,
    ) -> Result<Value> {
        let mut req = self
            .http
            .request(method, format!("{}{path}", self.base))
            .header("X-LRFF-Token", &self.token);
        if let Some(b) = body {
            req = req.json(b);
        }
        let resp = req
            .send()
            .await
            .context("the Bridge is not running — start it and try again")?;
        let status = resp.status();
        let value: Value = resp.json().await.unwrap_or(Value::Null);
        if !status.is_success() {
            bail!(
                "Bridge {status}: {}",
                value["error"].as_str().unwrap_or("no details")
            );
        }
        Ok(value)
    }

    async fn get(&self, path: &str) -> Result<Value> {
        self.call(reqwest::Method::GET, path, None).await
    }

    async fn post(&self, path: &str, body: &Value) -> Result<Value> {
        self.call(reqwest::Method::POST, path, Some(body)).await
    }

    /// Register photos; returns catalog-style id → photo.
    async fn register(
        &self,
        photos: Vec<FolderPhoto>,
        with_settings: bool,
    ) -> Result<HashMap<String, FolderPhoto>> {
        let mut by_id = HashMap::new();
        for (i, photo) in photos.into_iter().enumerate() {
            let id = folder::file_id(&photo.path)?;
            let path = std::path::absolute(&photo.path)?;
            let settings = if with_settings {
                photo.settings.clone()
            } else {
                Map::new()
            };
            self.post(
                "/v1/photos",
                &json!({
                    "schema_version": "bridge-photo-v1",
                    "lr_catalog_uuid": id,
                    "file_path": path.display().to_string(),
                    "lr_develop_settings": settings,
                    "lr_metadata": photo.decisions,
                }),
            )
            .await
            .with_context(|| format!("registering {}", photo.path.display()))?;
            if (i + 1) % 10 == 0 {
                println!("  registered {} photos", i + 1);
            }
            by_id.insert(id, photo);
        }
        Ok(by_id)
    }

    /// Poll until the job is completed or failed, printing status changes. A Bridge
    /// restart is survived (the job lives in its queue); after ~1 min without it we stop.
    async fn wait(&self, job_id: &str) -> Result<Value> {
        let mut last = String::new();
        let mut failures = 0;
        loop {
            let job = match self.get(&format!("/v1/jobs/{job_id}")).await {
                Ok(job) => {
                    failures = 0;
                    job
                }
                Err(e) if failures < 30 => {
                    failures += 1;
                    if failures == 1 {
                        println!("  Bridge not reachable, waiting ({e:#})");
                    }
                    tokio::time::sleep(Duration::from_secs(2)).await;
                    continue;
                }
                Err(e) => {
                    return Err(e.context(format!(
                        "gave up waiting; job {job_id} keeps running in the Bridge"
                    )))
                }
            };
            let status = job["status"].as_str().unwrap_or("?").to_string();
            if status != last {
                println!("  job {status}");
                last = status.clone();
            }
            match status.as_str() {
                "completed" => return Ok(job),
                "failed" => bail!(
                    "job failed: {}",
                    job["last_error"].as_str().unwrap_or("no reason")
                ),
                _ => tokio::time::sleep(Duration::from_secs(2)).await,
            }
        }
    }
}

/// Scan the folder, optionally keeping only the files named in a list.
fn scan_selected(dir: &Path, files_from: Option<&Path>) -> Result<Vec<FolderPhoto>> {
    let photos = folder::scan(dir)?;
    let Some(list) = files_from else {
        return Ok(photos);
    };
    let text =
        std::fs::read_to_string(list).with_context(|| format!("cannot read {}", list.display()))?;
    let wanted: std::collections::HashSet<String> = text
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .filter_map(|l| {
            Path::new(l)
                .file_name()
                .map(|n| n.to_string_lossy().to_lowercase())
        })
        .collect();
    let selected: Vec<FolderPhoto> = photos
        .into_iter()
        .filter(|p| {
            p.path
                .file_name()
                .is_some_and(|n| wanted.contains(&n.to_string_lossy().to_lowercase()))
        })
        .collect();
    println!("{} of {} listed files found", selected.len(), wanted.len());
    Ok(selected)
}

async fn train(
    bridge: &Bridge,
    dir: &Path,
    name: &str,
    genre: &str,
    color: &str,
    files_from: Option<&Path>,
    style: Option<&Path>,
) -> Result<()> {
    let base_preset = match style {
        Some(path) => {
            let text = std::fs::read_to_string(path)
                .with_context(|| format!("cannot read style preset {}", path.display()))?;
            let settings = xmp::read_develop_settings(&text);
            if settings.is_empty() {
                bail!("{} holds no develop settings", path.display());
            }
            println!(
                "style layer from {} ({} settings)",
                path.display(),
                settings.len()
            );
            Some(Value::Object(settings))
        }
        None => None,
    };
    let (edited, other): (Vec<_>, Vec<_>) = scan_selected(dir, files_from)?
        .into_iter()
        .partition(FolderPhoto::is_edited);
    println!(
        "{} edited RAWs for training, {} without develop settings ignored",
        edited.len(),
        other.len()
    );
    if edited.len() < 3 {
        bail!("need at least 3 edited RAWs (RAW + XMP with develop settings)");
    }
    let by_id = bridge.register(edited, true).await?;
    let job = bridge
        .post(
            "/v1/jobs/train",
            &json!({
                "schema_version": "bridge-train-v1",
                "profile_name": name,
                "genre": genre,
                "format_type": "raw",
                "color_type": color,
                "base_preset": base_preset,
                "lr_catalog_uuids": by_id.keys().collect::<Vec<_>>(),
            }),
        )
        .await?;
    let done = bridge
        .wait(job["job_id"].as_str().unwrap_or_default())
        .await?;
    println!(
        "profile \"{name}\" ready: {}",
        done["profile_id"].as_str().unwrap_or("?")
    );
    Ok(())
}

async fn find_profile(bridge: &Bridge, wanted: &str) -> Result<Value> {
    let profiles = bridge.get("/v1/profiles").await?;
    let matches: Vec<&Value> = profiles
        .as_array()
        .map(|a| {
            a.iter()
                .filter(|p| p["profile_id"] == wanted || p["name"] == wanted)
                .collect()
        })
        .unwrap_or_default();
    let ready: Vec<&&Value> = matches.iter().filter(|p| p["status"] == "ready").collect();
    match (matches.len(), ready.len()) {
        (0, _) => bail!("no profile \"{wanted}\" — see `lrff-folder profiles`"),
        (_, 0) => bail!("profile \"{wanted}\" is not ready yet"),
        (_, 1) => Ok((*ready[0]).clone()),
        _ => bail!("several ready profiles are called \"{wanted}\" — use the profile id"),
    }
}

async fn apply(
    bridge: &Bridge,
    dir: &Path,
    wanted: &str,
    force: bool,
    files_from: Option<&Path>,
    out: Option<&Path>,
) -> Result<()> {
    let profile = find_profile(bridge, wanted).await?;
    if profile["format_type"] != "raw" {
        bail!("folder mode writes RAW sidecars; this profile is for JPEG/TIFF");
    }
    let name = profile["name"].as_str().unwrap_or(wanted).to_string();
    // With --out nothing next to the RAWs is overwritten, so existing edits do not block.
    let (todo, edited): (Vec<_>, Vec<_>) = scan_selected(dir, files_from)?
        .into_iter()
        .partition(|p| force || out.is_some() || !p.is_edited());
    if let Some(out) = out {
        std::fs::create_dir_all(out)?;
    }
    println!(
        "{} RAWs to edit, {} already edited and skipped (use --force)",
        todo.len(),
        edited.len()
    );
    if todo.is_empty() {
        return Ok(());
    }
    let by_id = bridge.register(todo, false).await?;
    let job = bridge
        .post(
            "/v1/jobs/edit",
            &json!({
                "schema_version": "bridge-edit-v1",
                "profile_id": profile["profile_id"],
                "lr_catalog_uuids": by_id.keys().collect::<Vec<_>>(),
            }),
        )
        .await?;
    let done = bridge
        .wait(job["job_id"].as_str().unwrap_or_default())
        .await?;
    let mut written = 0;
    for result in done["results"].as_array().into_iter().flatten() {
        let (Some(id), Some(settings)) = (
            result["lr_catalog_uuid"].as_str(),
            result["lr_settings"].as_object(),
        ) else {
            continue;
        };
        if let Some(photo) = by_id.get(id) {
            match out {
                Some(out) => {
                    let mut target = photo.clone();
                    target.sidecar = out.join(photo.sidecar.file_name().unwrap_or_default());
                    folder::write_result(&target, settings, &name)?;
                }
                None => folder::write_result(photo, settings, &name)?,
            }
            written += 1;
        }
    }
    println!(
        "wrote {written} XMP sidecars ({} photos without result)",
        by_id.len() - written
    );
    Ok(())
}

async fn profiles(bridge: &Bridge) -> Result<()> {
    let list = bridge.get("/v1/profiles").await?;
    for p in list.as_array().into_iter().flatten() {
        println!(
            "{}  {:<8}  {:<9}  {}",
            p["profile_id"].as_str().unwrap_or("?"),
            p["status"].as_str().unwrap_or("?"),
            p["format_type"].as_str().unwrap_or("?"),
            p["name"].as_str().unwrap_or("?")
        );
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    let bridge = Bridge::connect()?;
    match cli.command {
        Command::Train {
            dir,
            name,
            genre,
            color,
            files_from,
            style,
        } => {
            train(
                &bridge,
                &dir,
                &name,
                &genre,
                &color,
                files_from.as_deref(),
                style.as_deref(),
            )
            .await
        }
        Command::Apply {
            dir,
            profile,
            force,
            files_from,
            out,
        } => {
            apply(
                &bridge,
                &dir,
                &profile,
                force,
                files_from.as_deref(),
                out.as_deref(),
            )
            .await
        }
        Command::Profiles => profiles(&bridge).await,
    }
}
