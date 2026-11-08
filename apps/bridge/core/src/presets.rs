//! The project's own looks and retouch presets (`presets/`, CC0), installed for Lightroom
//! Classic / Camera Raw so nobody has to copy files: the Bridge writes them on start into
//! `<Camera Raw settings>/Calotype/`, only when they changed. Lightroom picks them up at its
//! next start; the plugin finds the retouch presets there by group and name.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result};

/// Folder name inside Camera Raw's settings folder.
pub const FOLDER: &str = "Calotype";

/// (path below `presets/`, content). `presets_on_disk_are_all_embedded` keeps this in sync.
pub const PRESETS: &[(&str, &str)] = &[
    (
        "bright-airy.xmp",
        include_str!("../../../../presets/bright-airy.xmp"),
    ),
    (
        "clean-natural.xmp",
        include_str!("../../../../presets/clean-natural.xmp"),
    ),
    (
        "cool-modern.xmp",
        include_str!("../../../../presets/cool-modern.xmp"),
    ),
    (
        "film-bw.xmp",
        include_str!("../../../../presets/film-bw.xmp"),
    ),
    (
        "film-color.xmp",
        include_str!("../../../../presets/film-color.xmp"),
    ),
    (
        "golden-evening.xmp",
        include_str!("../../../../presets/golden-evening.xmp"),
    ),
    (
        "soft-bw.xmp",
        include_str!("../../../../presets/soft-bw.xmp"),
    ),
    (
        "warm-soft.xmp",
        include_str!("../../../../presets/warm-soft.xmp"),
    ),
    (
        "retouch/background.xmp",
        include_str!("../../../../presets/retouch/background.xmp"),
    ),
    (
        "retouch/eyes.xmp",
        include_str!("../../../../presets/retouch/eyes.xmp"),
    ),
    (
        "retouch/skin.xmp",
        include_str!("../../../../presets/retouch/skin.xmp"),
    ),
    (
        "retouch/sky.xmp",
        include_str!("../../../../presets/retouch/sky.xmp"),
    ),
    (
        "retouch/subject.xmp",
        include_str!("../../../../presets/retouch/subject.xmp"),
    ),
    (
        "retouch/teeth.xmp",
        include_str!("../../../../presets/retouch/teeth.xmp"),
    ),
];

/// Camera Raw's user settings folder (presets): `%APPDATA%\Adobe\CameraRaw\Settings` on Windows,
/// `~/Library/Application Support/Adobe/CameraRaw/Settings` on macOS.
pub fn camera_raw_settings_dir() -> Option<PathBuf> {
    Some(
        dirs::data_dir()?
            .join("Adobe")
            .join("CameraRaw")
            .join("Settings"),
    )
}

/// Folder names before the rename (ADR 006); the files we put there are removed.
pub const OLD_FOLDERS: [&str; 2] = ["Tarsier", "LR-FrameFlow"];

/// Write every preset below `settings_dir/Calotype`; returns how many files changed. Files this
/// Bridge once installed under the old folder name are removed (nothing else there is touched).
pub fn install(settings_dir: &Path) -> Result<usize> {
    for name in OLD_FOLDERS {
        let old = settings_dir.join(name);
        for (rel, _) in PRESETS {
            let _ = std::fs::remove_file(old.join(rel));
        }
        let _ = std::fs::remove_dir(old.join("retouch"));
        let _ = std::fs::remove_dir(&old);
    }
    let mut changed = 0;
    for (rel, content) in PRESETS {
        let target = settings_dir.join(FOLDER).join(rel);
        if std::fs::read_to_string(&target).ok().as_deref() == Some(*content) {
            continue;
        }
        std::fs::create_dir_all(target.parent().context("preset path without folder")?)?;
        std::fs::write(&target, content)
            .with_context(|| format!("cannot write {}", target.display()))?;
        changed += 1;
    }
    Ok(changed)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn installs_once_and_only_rewrites_changed_files() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(install(dir.path()).unwrap(), PRESETS.len());
        assert_eq!(install(dir.path()).unwrap(), 0);
        let one = dir.path().join(FOLDER).join(PRESETS[0].0);
        std::fs::write(&one, "edited").unwrap();
        assert_eq!(install(dir.path()).unwrap(), 1);
        assert!(dir.path().join(FOLDER).join("retouch/subject.xmp").exists());

        // Our files under the old folder name go away, a file of the user's stays.
        let old = dir.path().join(OLD_FOLDERS[1]);
        std::fs::create_dir_all(old.join("retouch")).unwrap();
        std::fs::write(old.join(PRESETS[0].0), "x").unwrap();
        std::fs::write(old.join("my-own.xmp"), "mine").unwrap();
        install(dir.path()).unwrap();
        assert!(!old.join(PRESETS[0].0).exists() && old.join("my-own.xmp").exists());
    }

    #[test]
    fn presets_on_disk_are_all_embedded() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../presets");
        let mut on_disk = Vec::new();
        for sub in ["", "retouch"] {
            for e in std::fs::read_dir(root.join(sub)).unwrap() {
                let p = e.unwrap().path();
                if p.extension().is_some_and(|x| x == "xmp") {
                    let name = p.file_name().unwrap().to_string_lossy().to_string();
                    on_disk.push(if sub.is_empty() {
                        name
                    } else {
                        format!("{sub}/{name}")
                    });
                }
            }
        }
        on_disk.sort();
        let mut embedded: Vec<String> = PRESETS.iter().map(|(p, _)| p.to_string()).collect();
        embedded.sort();
        assert_eq!(
            embedded, on_disk,
            "add new presets to PRESETS in presets.rs"
        );
    }
}
