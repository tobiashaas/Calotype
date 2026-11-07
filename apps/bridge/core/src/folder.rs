//! Folder mode: RAW files + XMP sidecars, no Lightroom needed.
//!
//! Photos outside a catalog get a stable, content-based id instead of a catalog UUID,
//! so moving or renaming the folder does not create new photos on the server.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use crate::xmp;

pub const RAW_EXTENSIONS: &[&str] = &[
    "cr2", "cr3", "crw", "nef", "nrw", "arw", "srf", "sr2", "raf", "dng", "orf", "rw2", "pef",
    "srw", "3fr", "iiq", "x3f", "erf", "mef", "mos", "kdc", "dcr",
];
const SAMPLE: u64 = 1 << 20;

pub fn is_raw(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .is_some_and(|e| RAW_EXTENSIONS.contains(&e.to_ascii_lowercase().as_str()))
}

/// `file-` + SHA-256 over size, first and last MiB: stable across moves and renames,
/// cheap even for 80 MB RAWs.
pub fn file_id(path: &Path) -> Result<String> {
    let mut f = File::open(path).with_context(|| format!("cannot open {}", path.display()))?;
    let len = f.metadata()?.len();
    let mut hasher = Sha256::new();
    hasher.update(len.to_le_bytes());
    let mut buf = vec![0u8; SAMPLE.min(len) as usize];
    f.read_exact(&mut buf)?;
    hasher.update(&buf);
    if len > SAMPLE {
        let tail = SAMPLE.min(len - SAMPLE);
        f.seek(SeekFrom::End(-(tail as i64)))?;
        let mut buf = vec![0u8; tail as usize];
        f.read_exact(&mut buf)?;
        hasher.update(&buf);
    }
    let digest = hasher.finalize();
    Ok(format!("file-{}", hex(&digest[..16])))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

#[derive(Debug, Clone)]
pub struct FolderPhoto {
    pub path: PathBuf,
    pub sidecar: PathBuf,
    /// Develop settings from an existing sidecar (empty if none or no crs: settings).
    pub settings: Map<String, Value>,
    /// Rating / color label from the sidecar (culling labels).
    pub decisions: Map<String, Value>,
    pub has_sidecar: bool,
}

impl FolderPhoto {
    pub fn is_edited(&self) -> bool {
        xmp::has_develop_settings(&self.settings)
    }
}

/// RAW files directly in `dir` (not recursive), sorted by name.
pub fn scan(dir: &Path) -> Result<Vec<FolderPhoto>> {
    scan_with_sidecars(dir, None)
}

/// Like [`scan`], but the sidecars may live in another folder (same file names). Lets
/// edits that exist only in a catalog be exported as XMPs without touching the RAW folder.
pub fn scan_with_sidecars(dir: &Path, sidecars: Option<&Path>) -> Result<Vec<FolderPhoto>> {
    let mut photos = Vec::new();
    for entry in std::fs::read_dir(dir).with_context(|| format!("cannot read {}", dir.display()))? {
        let path = entry?.path();
        if !path.is_file() || !is_raw(&path) {
            continue;
        }
        let mut sidecar = xmp::sidecar_path(&path);
        if let (Some(other), Some(name)) = (sidecars, sidecar.file_name()) {
            sidecar = other.join(name);
        }
        let (has_sidecar, settings, decisions) = match std::fs::read_to_string(&sidecar) {
            Ok(text) => (
                true,
                xmp::read_develop_settings(&text),
                xmp::read_decisions(&text),
            ),
            Err(_) => (false, Map::new(), Map::new()),
        };
        photos.push(FolderPhoto {
            path,
            sidecar,
            settings,
            decisions,
            has_sidecar,
        });
    }
    photos.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(photos)
}

/// Write predicted settings next to the RAW: new sidecar, or update an existing one.
pub fn write_result(
    photo: &FolderPhoto,
    settings: &Map<String, Value>,
    profile: &str,
) -> Result<()> {
    let text = if photo.sidecar.exists() {
        let existing = std::fs::read_to_string(&photo.sidecar)?;
        xmp::update_sidecar(&existing, settings, profile)
            .with_context(|| format!("cannot update {}", photo.sidecar.display()))?
    } else {
        xmp::new_sidecar(settings, profile)
    };
    let tmp = photo.sidecar.with_extension("xmp.lrff-tmp");
    std::fs::write(&tmp, text)?;
    std::fs::rename(&tmp, &photo.sidecar)
        .with_context(|| format!("cannot write {}", photo.sidecar.display()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn id_is_stable_across_copies_and_differs_by_content() {
        let dir = tempfile::tempdir().unwrap();
        let a = dir.path().join("a.CR3");
        let b = dir.path().join("renamed.cr3");
        let c = dir.path().join("c.cr3");
        let data: Vec<u8> = (0..3_000_000u32).map(|i| (i % 251) as u8).collect();
        std::fs::write(&a, &data).unwrap();
        std::fs::write(&b, &data).unwrap();
        let mut other = data.clone();
        *other.last_mut().unwrap() ^= 1;
        std::fs::write(&c, other).unwrap();
        assert_eq!(file_id(&a).unwrap(), file_id(&b).unwrap());
        assert_ne!(file_id(&a).unwrap(), file_id(&c).unwrap());
        assert!(file_id(&a).unwrap().starts_with("file-"));
    }

    #[test]
    fn scan_finds_raws_and_reads_sidecars() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("IMG_1.CR3"), b"raw").unwrap();
        std::fs::write(dir.path().join("IMG_2.nef"), b"raw").unwrap();
        std::fs::write(dir.path().join("notes.txt"), b"x").unwrap();
        std::fs::write(
            dir.path().join("IMG_1.xmp"),
            r#"<rdf:Description crs:Exposure2012="+0.50" crs:Temperature="5600"/>"#,
        )
        .unwrap();
        let photos = scan(dir.path()).unwrap();
        assert_eq!(photos.len(), 2);
        assert!(photos[0].is_edited());
        assert_eq!(photos[0].settings["Temperature"], serde_json::json!(5600));
        assert!(!photos[1].has_sidecar && !photos[1].is_edited());
    }

    #[test]
    fn sidecars_can_live_in_another_folder() {
        let raws = tempfile::tempdir().unwrap();
        let side = tempfile::tempdir().unwrap();
        std::fs::write(raws.path().join("a.cr3"), b"raw").unwrap();
        std::fs::write(
            side.path().join("a.xmp"),
            r#"<x:xmpmeta><rdf:Description crs:Exposure2012="+0.50"/></x:xmpmeta>"#,
        )
        .unwrap();
        let photos = scan_with_sidecars(raws.path(), Some(side.path())).unwrap();
        assert!(photos[0].has_sidecar && photos[0].is_edited());
        assert!(!scan(raws.path()).unwrap()[0].has_sidecar);
    }

    #[test]
    fn write_result_creates_then_updates_sidecar() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("A.CR3"), b"raw").unwrap();
        let photo = scan(dir.path()).unwrap().remove(0);
        let mut s = Map::new();
        s.insert("Exposure2012".into(), serde_json::json!(0.3));
        write_result(&photo, &s, "P1").unwrap();
        let written = std::fs::read_to_string(&photo.sidecar).unwrap();
        assert!(written.contains("crs:Exposure2012=\"+0.30\""));
        s.insert("Exposure2012".into(), serde_json::json!(-0.1));
        write_result(&photo, &s, "P2").unwrap();
        let updated = std::fs::read_to_string(&photo.sidecar).unwrap();
        assert!(
            updated.contains("crs:Exposure2012=\"-0.10\"")
                && updated.contains("lrff:Profile=\"P2\"")
        );
    }
}
