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
    // "._x.CR2" are macOS metadata files (copies from a Mac or a NAS), not photos.
    if path
        .file_name()
        .is_some_and(|n| n.to_string_lossy().starts_with("._"))
    {
        return false;
    }
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

/// Lightroom catalogs (`*.lrcat`) directly in `dir` (macOS `._` copies skipped).
pub fn catalogs_in(dir: &Path) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return Vec::new();
    };
    let mut out: Vec<PathBuf> = entries
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| {
            p.is_file()
                && p.extension()
                    .is_some_and(|e| e.eq_ignore_ascii_case("lrcat"))
                && !p
                    .file_name()
                    .is_some_and(|n| n.to_string_lossy().starts_with("._"))
        })
        .collect();
    out.sort();
    out
}

/// Take develop settings and decisions from Lightroom catalogs: for each photo the nearest
/// catalog above it that knows the file wins over the sidecar (the catalog is Lightroom's
/// own state; sidecars may be older or missing). A photo the catalog lists as only imported
/// or reset counts as not edited. Returns (photos found in a catalog, of them edited).
pub fn apply_catalogs(
    photos: &mut [FolderPhoto],
    catalogs: &[(PathBuf, crate::catalog::Catalog)],
) -> (usize, usize) {
    let (mut found, mut edited) = (0, 0);
    for photo in photos.iter_mut() {
        // Nearest catalog first; one further up is asked when it does not know the file.
        let mut near: Vec<_> = catalogs
            .iter()
            .filter(|(dir, _)| photo.path.starts_with(dir))
            .collect();
        near.sort_by_key(|(dir, _)| std::cmp::Reverse(dir.components().count()));
        let entry = near.into_iter().find_map(|(_, c)| c.find(&photo.path));
        let Some(entry) = entry else {
            continue;
        };
        found += 1;
        photo.settings = if entry.edited {
            edited += 1;
            entry.settings.clone()
        } else {
            Map::new()
        };
        for (k, v) in &entry.decisions {
            photo.decisions.insert(k.clone(), v.clone());
        }
    }
    (found, edited)
}

/// `root` and every folder below it, sorted. Skips what is not the photographer's photos:
/// Lightroom's preview folders (`*.lrdata` — smart previews are DNG files), hidden folders
/// (`.AppleDouble`, `.Trash`) and NAS metadata (`@eaDir`, `@tmp`).
pub fn photo_dirs(root: &Path) -> Result<Vec<PathBuf>> {
    let mut out = vec![root.to_path_buf()];
    let mut i = 0;
    while i < out.len() {
        let dir = out[i].clone();
        i += 1;
        let entries =
            std::fs::read_dir(&dir).with_context(|| format!("cannot read {}", dir.display()))?;
        for entry in entries {
            let path = entry?.path();
            let name = path
                .file_name()
                .map(|n| n.to_string_lossy().to_lowercase())
                .unwrap_or_default();
            let skip = name.starts_with('.') || name.starts_with('@') || name.ends_with(".lrdata");
            if !skip && path.is_dir() {
                out.push(path);
            }
        }
    }
    out.sort();
    Ok(out)
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
    let tmp = photo.sidecar.with_extension("xmp.calotype-tmp");
    std::fs::write(&tmp, text)?;
    std::fs::rename(&tmp, &photo.sidecar)
        .with_context(|| format!("cannot write {}", photo.sidecar.display()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn photo_dirs_skip_previews_and_metadata() {
        let root = tempfile::tempdir().unwrap();
        for d in [
            "2015/Wedding A/Bilder",
            "2015/Wedding A/Wedding A Smart Previews.lrdata/0",
            "2015/Wedding A/.AppleDouble",
            "2015/@eaDir",
            "2016/Wedding B",
        ] {
            std::fs::create_dir_all(root.path().join(d)).unwrap();
        }
        let rel: Vec<String> = photo_dirs(root.path())
            .unwrap()
            .iter()
            .map(|p| {
                p.strip_prefix(root.path())
                    .unwrap()
                    .to_string_lossy()
                    .replace('\\', "/")
            })
            .collect();
        assert_eq!(
            rel,
            [
                "",
                "2015",
                "2015/Wedding A",
                "2015/Wedding A/Bilder",
                "2016",
                "2016/Wedding B"
            ]
        );
    }

    #[test]
    fn mac_metadata_files_are_not_raws() {
        assert!(is_raw(Path::new("IMG_1.CR2")));
        assert!(!is_raw(Path::new("._IMG_1.CR2")));
        assert!(!is_raw(Path::new("IMG_1.xmp")));
    }

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
                && updated.contains("calotype:Profile=\"P2\"")
        );
    }
}
