//! Collect one shoot for `tools/eval/shoot_pool.py`: previews plus, per photo, the edits the
//! catalog holds (read-only), the camera's measured colour temperature and the capture time.
//!
//!     cargo run --release -p calotype-bridge-core --example pool -- <out-dir> <catalog.lrcat> <raw-dir>
//!
//! Writes `<out-dir>/previews/<name>.jpg` and `<out-dir>/photos.jsonl`. Nothing is written
//! next to the photos or the catalog.

use std::io::Write;
use std::path::{Path, PathBuf};

use calotype_bridge_core::{catalog::Catalog, preview, whitebalance};
use serde_json::json;

const RAW: &[&str] = &["cr2", "cr3", "nef", "arw", "raf", "dng", "orf", "rw2"];

fn raws(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with('.') || name.ends_with(".lrdata") {
            continue;
        }
        if path.is_dir() {
            raws(&path, out);
        } else if path
            .extension()
            .map(|e| RAW.contains(&e.to_string_lossy().to_lowercase().as_str()))
            .unwrap_or(false)
        {
            out.push(path);
        }
    }
}

fn main() {
    let args: Vec<PathBuf> = std::env::args_os().skip(1).map(PathBuf::from).collect();
    let [out_dir, catalog_path, raw_dir] = args.as_slice() else {
        eprintln!("usage: pool <out-dir> <catalog.lrcat> <raw-dir>");
        std::process::exit(2);
    };
    let catalog = Catalog::open(catalog_path).expect("open catalog read-only");
    let previews = out_dir.join("previews");
    std::fs::create_dir_all(&previews).expect("create out dir");
    let mut files = Vec::new();
    raws(raw_dir, &mut files);
    files.sort();
    let mut lines =
        std::fs::File::create(out_dir.join("photos.jsonl")).expect("create photos.jsonl");
    let (mut edited, mut unknown, mut failed) = (0, 0, 0);
    for file in &files {
        let Some(photo) = catalog.find(file) else {
            unknown += 1;
            continue;
        };
        let name = file
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        match preview::build_preview(file) {
            Ok(jpeg) => {
                std::fs::write(previews.join(format!("{name}.jpg")), jpeg).expect("write preview")
            }
            Err(e) => {
                failed += 1;
                eprintln!("no preview for {}: {e}", file.display());
                continue;
            }
        }
        edited += usize::from(photo.edited);
        let line = json!({
            "name": name,
            "file": file.display().to_string(),
            "edited": photo.edited,
            "settings": photo.settings,
            "decisions": photo.decisions,
            "wb_measured_kelvin": whitebalance::measured_kelvin(file),
            "date_time_original": preview::capture_time(file),
        });
        writeln!(lines, "{line}").expect("write line");
    }
    println!(
        "{} RAW files: {} edited, {} not in the catalog, {} without preview",
        files.len(),
        edited,
        unknown,
        failed
    );
}
