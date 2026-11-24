//! A look from the photographer's own Lightroom / Camera Raw develop presets, for folder mode
//! (`calotype-folder apply --look`, `train --style`).
//!
//! The same rules as the plugin's `LookPresets.lua`: plain values and tone curves only —
//! masks and other nested settings belong to the photo the preset was made on — and Lightroom's
//! "Default Profile" placeholder is left out (it would replace the photo's camera profile).
//! The settings go to the server as `base_preset`; its style layer decides what of them is the
//! look. Presets are only read, never copied or stored.

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde_json::{Map, Value};

use crate::xmp;

/// Bookkeeping of a preset file, not a develop setting (Lightroom's `preset:getSetting()` does
/// not return these either).
const PRESET_FILE_KEYS: [&str; 18] = [
    "PresetType",
    "Cluster",
    "UUID",
    "SupportsAmount",
    "SupportsAmount2",
    "SupportsColor",
    "SupportsMonochrome",
    "SupportsHighDynamicRange",
    "SupportsNormalDynamicRange",
    "SupportsSceneReferred",
    "SupportsOutputReferred",
    "CameraModelRestriction",
    "Copyright",
    "ContactInfo",
    "Version",
    "HasSettings",
    "RequiresRGBTables",
    "Group",
];

/// Lightroom's placeholder for "the preset names no camera profile".
const NO_PROFILE: &str = "Default Profile";

/// The look settings of a preset's XMP text: top-level `crs:` values and tone curves.
pub fn look_settings(preset_xmp: &str) -> Map<String, Value> {
    let mut settings = xmp::read_develop_settings(preset_xmp);
    settings.retain(|key, value| {
        !PRESET_FILE_KEYS.contains(&key.as_str())
            && !(key == "CameraProfile" && value.as_str() == Some(NO_PROFILE))
    });
    settings
}

/// A preset's display name (`crs:Name`, its default language), if it has one.
pub fn preset_name(preset_xmp: &str) -> Option<String> {
    let start = preset_xmp.find("<crs:Name>")?;
    let end = start + preset_xmp[start..].find("</crs:Name>")?;
    let element = &preset_xmp[start..end];
    let li = element.find("<rdf:li")?;
    let text_start = li + element[li..].find('>')? + 1;
    let text_end = text_start + element[text_start..].find("</rdf:li>")?;
    let name = xmp::unescape(element[text_start..text_end].trim());
    (!name.is_empty()).then_some(name)
}

/// Every `.xmp` below `dir` (Camera Raw keeps presets in group folders).
fn preset_files(dir: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&d) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            } else if path
                .extension()
                .is_some_and(|e| e.eq_ignore_ascii_case("xmp"))
            {
                out.push(path);
            }
        }
    }
    out.sort();
    out
}

/// The installed preset called `wanted` (its name, or its file name without `.xmp`; case does
/// not matter) below Camera Raw's settings folder. Ambiguous names are an error.
pub fn find_installed(settings_dir: &Path, wanted: &str) -> Result<PathBuf> {
    let wanted = wanted.trim().to_lowercase();
    let mut hits: Vec<PathBuf> = preset_files(settings_dir)
        .into_iter()
        .filter(|path| {
            let stem = path.file_stem().map(|s| s.to_string_lossy().to_lowercase());
            let name = std::fs::read_to_string(path)
                .ok()
                .and_then(|text| preset_name(&text))
                .map(|n| n.to_lowercase());
            stem.as_deref() == Some(wanted.as_str()) || name.as_deref() == Some(wanted.as_str())
        })
        .collect();
    match hits.len() {
        0 => bail!(
            "no preset called '{wanted}' in {} — pass the path of its .xmp file",
            settings_dir.display()
        ),
        1 => Ok(hits.remove(0)),
        _ => bail!(
            "{} presets are called '{wanted}': {} — pass the path of one",
            hits.len(),
            hits.iter()
                .map(|p| p.display().to_string())
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

/// A look: an `.xmp` preset file, or the name of a preset installed in `settings_dir`.
/// Returns the preset's name (or file name) and its look settings.
pub fn read_look(spec: &str, settings_dir: Option<&Path>) -> Result<(String, Map<String, Value>)> {
    let given = Path::new(spec);
    let path = if given.is_file() {
        given.to_path_buf()
    } else {
        let Some(dir) = settings_dir else {
            bail!("'{spec}' is no file, and Camera Raw's settings folder is unknown here");
        };
        find_installed(dir, spec)?
    };
    let text = std::fs::read_to_string(&path)
        .with_context(|| format!("cannot read preset {}", path.display()))?;
    let settings = look_settings(&text);
    if settings.is_empty() {
        bail!("{} holds no develop settings", path.display());
    }
    let name = preset_name(&text).unwrap_or_else(|| {
        path.file_stem()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_else(|| spec.to_string())
    });
    Ok((name, settings))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const PRESET: &str = r#"<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    crs:PresetType="Normal"
    crs:UUID="573EF0AC03BA4B20BE8FF12A75B8F5AF"
    crs:SupportsAmount="False"
    crs:Version="15.4"
    crs:HasSettings="True"
    crs:Contrast2012="12"
    crs:Highlights2012="-45"
    crs:GrainAmount="15"
    crs:ConvertToGrayscale="False"
    crs:CameraProfile="Default Profile">
   <crs:Name>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">Warm &amp; Soft</rdf:li>
    </rdf:Alt>
   </crs:Name>
   <crs:ToneCurvePV2012>
    <rdf:Seq>
     <rdf:li>0, 20</rdf:li>
     <rdf:li>255, 240</rdf:li>
    </rdf:Seq>
   </crs:ToneCurvePV2012>
   <crs:MaskGroupBasedCorrections>
    <rdf:Seq>
     <rdf:li>
      <rdf:Description crs:LocalExposure2012="0.5"/>
     </rdf:li>
    </rdf:Seq>
   </crs:MaskGroupBasedCorrections>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"#;

    #[test]
    fn look_keeps_plain_values_and_curves_only() {
        assert_eq!(
            Value::Object(look_settings(PRESET)),
            json!({
                "Contrast2012": 12,
                "Highlights2012": -45,
                "GrainAmount": 15,
                "ConvertToGrayscale": "False",
                "ToneCurvePV2012": [0.0, 20.0, 255.0, 240.0],
            }),
            "no preset bookkeeping, no placeholder profile, no masks"
        );
        let named = PRESET.replace("Default Profile", "Adobe Portrait");
        assert_eq!(look_settings(&named)["CameraProfile"], "Adobe Portrait");
    }

    #[test]
    fn preset_name_is_the_default_language_title() {
        assert_eq!(preset_name(PRESET).as_deref(), Some("Warm & Soft"));
        assert_eq!(preset_name("<x:xmpmeta/>"), None);
    }

    #[test]
    fn look_by_file_or_by_installed_name() {
        let dir = tempfile::tempdir().unwrap();
        let group = dir.path().join("My Looks");
        std::fs::create_dir_all(&group).unwrap();
        let file = group.join("warm-soft.xmp");
        std::fs::write(&file, PRESET).unwrap();
        std::fs::write(
            group.join("other.xmp"),
            PRESET.replace("Warm &amp;", "Cold &amp;"),
        )
        .unwrap();

        let (name, settings) = read_look(file.to_str().unwrap(), None).unwrap();
        assert_eq!(
            (name.as_str(), settings["Contrast2012"].clone()),
            ("Warm & Soft", json!(12))
        );
        for wanted in ["warm & soft", "WARM-SOFT", " Warm & Soft "] {
            let (name, _) = read_look(wanted, Some(dir.path())).unwrap();
            assert_eq!(name, "Warm & Soft", "{wanted}");
        }
        let missing = read_look("Nope", Some(dir.path())).unwrap_err();
        assert!(missing.to_string().contains("no preset called 'nope'"));
        assert!(read_look("Nope", None).is_err());

        std::fs::write(group.join("twin.xmp"), PRESET).unwrap();
        let twice = read_look("Warm & Soft", Some(dir.path())).unwrap_err();
        assert!(twice.to_string().contains("2 presets"), "{twice}");

        let empty = dir.path().join("empty.xmp");
        std::fs::write(&empty, "<x:xmpmeta/>").unwrap();
        assert!(read_look(empty.to_str().unwrap(), None).is_err());
    }
}
