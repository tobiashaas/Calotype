//! Read develop settings and ratings from a Lightroom Classic catalog (`.lrcat`), without
//! Lightroom and without changing the file: older shoots often keep their edits only in the
//! catalog, not in XMP sidecars.
//!
//! The catalog is opened read-only and `immutable` (no locks, no journal next to it). Paths in a
//! catalog point to where the photos were back then (another computer, a NAS), so photos are
//! matched by file name below the catalog's folder, not by the stored path.

use std::collections::HashMap;
use std::path::Path;

use anyhow::{Context, Result};
use rusqlite::{Connection, OpenFlags};
use serde_json::{Map, Value};

use crate::xmp;

/// One photo as the catalog knows it.
#[derive(Debug, Clone)]
pub struct CatalogPhoto {
    /// File name with extension, e.g. `IMG_0001.CR2`.
    pub file_name: String,
    /// Name of the folder the photo was in (last part of the stored path), for duplicates.
    pub folder_name: String,
    /// Develop settings with XMP names and types (as `xmp::read_develop_settings` returns them).
    pub settings: Map<String, Value>,
    /// Rating / pick / color label in the form of `xmp::read_decisions`.
    pub decisions: Map<String, Value>,
    /// The photographer worked on it: the last history step is neither the import (with or
    /// without an import preset) nor "reset settings".
    pub edited: bool,
}

/// Photos of a catalog, by lower-case file name (a name can occur in several folders).
pub struct Catalog {
    pub photos: HashMap<String, Vec<CatalogPhoto>>,
}

impl Catalog {
    pub fn open(path: &Path) -> Result<Self> {
        let conn = Connection::open_with_flags(
            sqlite_uri(path),
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI,
        )
        .with_context(|| format!("cannot open catalog {}", path.display()))?;
        let photos = read_photos(&conn)
            .with_context(|| format!("cannot read catalog {}", path.display()))?;
        let mut by_name: HashMap<String, Vec<CatalogPhoto>> = HashMap::new();
        for p in photos {
            by_name
                .entry(p.file_name.to_lowercase())
                .or_default()
                .push(p);
        }
        Ok(Self { photos: by_name })
    }

    /// The catalog's entry for a file, if it is unambiguous (same name in two folders: the
    /// folder name decides).
    pub fn find(&self, file: &Path) -> Option<&CatalogPhoto> {
        let name = file.file_name()?.to_string_lossy().to_lowercase();
        let entries = self.photos.get(&name)?;
        if let [only] = entries.as_slice() {
            return Some(only);
        }
        let folder = file.parent()?.file_name()?.to_string_lossy().to_lowercase();
        let mut same_folder = entries
            .iter()
            .filter(|e| e.folder_name.to_lowercase() == folder);
        match (same_folder.next(), same_folder.next()) {
            (Some(one), None) => Some(one),
            _ => None,
        }
    }

    pub fn len(&self) -> usize {
        self.photos.values().map(Vec::len).sum()
    }

    pub fn is_empty(&self) -> bool {
        self.photos.is_empty()
    }
}

/// `file:` URI with `immutable=1`: SQLite then never writes, locks or creates a journal.
fn sqlite_uri(path: &Path) -> String {
    let mut p = path.to_string_lossy().replace('\\', "/");
    if !p.starts_with('/') {
        p.insert(0, '/'); // Windows: file:/E:/...
    }
    let mut out = String::from("file:");
    for c in p.chars() {
        match c {
            ' ' => out.push_str("%20"),
            '%' => out.push_str("%25"),
            '#' => out.push_str("%23"),
            '?' => out.push_str("%3F"),
            '&' => out.push_str("%26"),
            _ => out.push(c),
        }
    }
    out.push_str("?mode=ro&immutable=1");
    out
}

fn read_photos(conn: &Connection) -> Result<Vec<CatalogPhoto>> {
    let last_steps = last_history_steps(conn)?;
    let mut stmt = conn.prepare(
        "SELECT i.id_local, f.baseName, f.extension, fo.pathFromRoot, s.text,
                i.rating, i.pick, i.colorLabels
         FROM Adobe_images i
         JOIN AgLibraryFile f ON f.id_local = i.rootFile
         JOIN AgLibraryFolder fo ON fo.id_local = f.folder
         LEFT JOIN Adobe_imageDevelopSettings s ON s.image = i.id_local",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, Option<String>>(3)?,
            r.get::<_, Option<String>>(4)?,
            r.get::<_, Option<f64>>(5)?,
            r.get::<_, Option<f64>>(6)?,
            r.get::<_, Option<String>>(7)?,
        ))
    })?;
    let mut out = Vec::new();
    for row in rows {
        let (id, base, ext, folder, text, rating, pick, label) = row?;
        let settings = text.as_deref().map(parse_settings).unwrap_or_default();
        let edited = xmp::has_develop_settings(&settings)
            && last_steps.get(&id).is_some_and(|name| is_own_step(name));
        let folder_name = folder
            .unwrap_or_default()
            .trim_end_matches('/')
            .rsplit('/')
            .next()
            .unwrap_or_default()
            .to_string();
        out.push(CatalogPhoto {
            file_name: format!("{base}.{ext}"),
            folder_name,
            settings,
            decisions: decisions(rating, pick, label.as_deref()),
            edited,
        });
    }
    Ok(out)
}

/// Name of the newest develop history step per image.
fn last_history_steps(conn: &Connection) -> Result<HashMap<i64, String>> {
    let mut stmt = conn.prepare(
        "SELECT h.image, h.name FROM Adobe_libraryImageDevelopHistoryStep h
         JOIN (SELECT image, MAX(id_local) AS last FROM Adobe_libraryImageDevelopHistoryStep
               GROUP BY image) x ON x.last = h.id_local",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok((r.get::<_, i64>(0)?, r.get::<_, Option<String>>(1)?))
    })?;
    let mut out = HashMap::new();
    for row in rows {
        let (image, name) = row?;
        out.insert(image, name.unwrap_or_default());
    }
    Ok(out)
}

/// A history step the photographer made — not the import (Lightroom names it "Import (date)",
/// German "Importieren (date)") and not "reset settings". Lightroom stores these names in the
/// UI language; English and German are recognised.
fn is_own_step(name: &str) -> bool {
    let n = name.trim().to_lowercase();
    !(n.is_empty()
        || n.starts_with("import")
        || n.starts_with("reset")
        || n.starts_with("einstellungen zurücksetzen"))
}

fn decisions(rating: Option<f64>, pick: Option<f64>, label: Option<&str>) -> Map<String, Value> {
    let mut out = Map::new();
    if let Some(r) = rating.filter(|r| (0.0..=5.0).contains(r)) {
        out.insert("rating".into(), Value::from(r.round() as i64));
    }
    match pick.map(|p| p.round() as i64) {
        Some(1) => {
            out.insert("pick_status".into(), Value::from(1));
        }
        Some(-1) => {
            out.insert("pick_status".into(), Value::from(-1));
        }
        _ => {}
    }
    if let Some(l) = label
        .map(|l| l.trim().to_lowercase())
        .filter(|l| !l.is_empty())
    {
        out.insert("color_label".into(), Value::from(l));
    }
    out
}

/// Lightroom stores settings as a Lua table: `s = { Exposure2012 = 0.5, WhiteBalance = "As
/// Shot", ToneCurvePV2012 = { 0, 0, 255, 255, }, … }`. Top-level numbers, strings and booleans
/// become values like in an XMP sidecar; tone curves become point lists; other nested tables
/// (masks, lens profiles) are skipped.
pub fn parse_settings(text: &str) -> Map<String, Value> {
    let mut out = Map::new();
    let Some(open) = text.find('{') else {
        return out;
    };
    let chars: Vec<char> = text[open + 1..].chars().collect();
    let mut i = 0;
    while i < chars.len() {
        skip_space_and_commas(&chars, &mut i);
        if i >= chars.len() || chars[i] == '}' {
            break;
        }
        let start = i;
        while i < chars.len() && (chars[i].is_alphanumeric() || chars[i] == '_') {
            i += 1;
        }
        let key: String = chars[start..i].iter().collect();
        skip_space_and_commas(&chars, &mut i);
        if key.is_empty() || i >= chars.len() || chars[i] != '=' {
            // Not `key = value` (e.g. an array element): skip one value.
            skip_value(&chars, &mut i);
            continue;
        }
        i += 1;
        while i < chars.len() && chars[i].is_whitespace() {
            i += 1;
        }
        match chars.get(i) {
            Some('"') => {
                let s = read_string(&chars, &mut i);
                out.insert(key, xmp::parse_value(&s));
            }
            Some('{') => {
                let start = i;
                skip_value(&chars, &mut i);
                if xmp::is_curve_key(&key) {
                    let inner: String = chars[start + 1..i.saturating_sub(1)].iter().collect();
                    let numbers: Option<Vec<f64>> = inner
                        .split(',')
                        .map(str::trim)
                        .filter(|s| !s.is_empty())
                        .map(|s| s.parse::<f64>().ok())
                        .collect();
                    if let Some(n) = numbers.filter(|n| !n.is_empty() && n.len() % 2 == 0) {
                        out.insert(key, Value::Array(n.into_iter().map(Value::from).collect()));
                    }
                }
            }
            Some(_) => {
                let start = i;
                while i < chars.len() && chars[i] != ',' && chars[i] != '}' && chars[i] != '\n' {
                    i += 1;
                }
                let raw: String = chars[start..i].iter().collect();
                let raw = raw.trim();
                let value = match raw {
                    "true" => Value::from("True"),
                    "false" => Value::from("False"),
                    _ => xmp::parse_value(raw),
                };
                out.insert(key, value);
            }
            None => break,
        }
    }
    out
}

fn skip_space_and_commas(chars: &[char], i: &mut usize) {
    while *i < chars.len() && (chars[*i].is_whitespace() || chars[*i] == ',') {
        *i += 1;
    }
}

/// Reads a Lua string starting at the opening quote; leaves `i` after the closing quote.
fn read_string(chars: &[char], i: &mut usize) -> String {
    let mut s = String::new();
    *i += 1;
    while *i < chars.len() {
        match chars[*i] {
            '\\' if *i + 1 < chars.len() => {
                *i += 1;
                s.push(match chars[*i] {
                    'n' => '\n',
                    't' => '\t',
                    c => c,
                });
            }
            '"' => {
                *i += 1;
                return s;
            }
            c => s.push(c),
        }
        *i += 1;
    }
    s
}

/// Skips one value (string, nested table or bare word); leaves `i` after it.
fn skip_value(chars: &[char], i: &mut usize) {
    match chars.get(*i) {
        Some('"') => {
            read_string(chars, i);
        }
        Some('{') => {
            let mut depth = 0;
            while *i < chars.len() {
                match chars[*i] {
                    '"' => {
                        read_string(chars, i);
                        continue;
                    }
                    '{' => depth += 1,
                    '}' => {
                        depth -= 1;
                        if depth == 0 {
                            *i += 1;
                            return;
                        }
                    }
                    _ => {}
                }
                *i += 1;
            }
        }
        _ => {
            while *i < chars.len() && !matches!(chars[*i], ',' | '}') {
                *i += 1;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEXT: &str = r#"s = { AutoGrayscaleMix = true,
	Blacks2012 = -5,
	CameraProfile = "Adobe Standard",
	ConvertToGrayscale = false,
	Exposure2012 = 0.35,
	MaskGroupBasedCorrections = { { What = "Correction", CorrectionAmount = 1, Masks = { { What = "Mask/Image" } } } },
	ProcessVersion = "11.0",
	Temperature = 4850,
	Tint = -7,
	ToneCurveName2012 = "Linear",
	ToneCurvePV2012 = { 0, 0, 64, 60, 255, 255, },
	WhiteBalance = "Custom",
	Title = "a \"quoted\" name",
}"#;

    #[test]
    fn lua_settings_become_xmp_like_values() {
        let s = parse_settings(TEXT);
        assert_eq!(s["Exposure2012"], Value::from(0.35));
        assert_eq!(s["Temperature"], Value::from(4850));
        assert_eq!(s["Tint"], Value::from(-7));
        assert_eq!(s["Blacks2012"], Value::from(-5));
        assert_eq!(s["WhiteBalance"], Value::from("Custom"));
        assert_eq!(s["ProcessVersion"], Value::from(11.0)); // like "11.0" read from an XMP
        assert_eq!(s["ConvertToGrayscale"], Value::from("False"));
        assert_eq!(s["AutoGrayscaleMix"], Value::from("True"));
        assert_eq!(s["Title"], Value::from("a \"quoted\" name"));
        assert_eq!(
            s["ToneCurvePV2012"],
            serde_json::json!([0.0, 0.0, 64.0, 60.0, 255.0, 255.0])
        );
        assert!(!s.contains_key("MaskGroupBasedCorrections"));
        assert!(xmp::has_develop_settings(&s));
    }

    #[test]
    fn own_steps_are_neither_import_nor_reset() {
        assert!(!is_own_step("Importieren (21.12.17 10:18:00)"));
        assert!(!is_own_step("Import (12/21/17 10:18:00)"));
        assert!(!is_own_step("Einstellungen zurücksetzen"));
        assert!(!is_own_step("Reset Settings"));
        assert!(is_own_step("Belichtung"));
        assert!(is_own_step("Einstellungen synchronisieren"));
        assert!(is_own_step("Paste Settings"));
    }

    #[test]
    fn uri_is_read_only_and_escaped() {
        let uri = sqlite_uri(Path::new(r"E:\2019\Nicole&Matze 8.6\x #1.lrcat"));
        assert_eq!(
            uri,
            "file:/E:/2019/Nicole%26Matze%208.6/x%20%231.lrcat?mode=ro&immutable=1"
        );
    }

    /// A tiny catalog with the tables and columns Lightroom uses.
    fn fake_catalog(path: &Path) {
        let c = Connection::open(path).unwrap();
        c.execute_batch(
            r#"
            CREATE TABLE AgLibraryFolder (id_local INTEGER PRIMARY KEY, pathFromRoot TEXT);
            CREATE TABLE AgLibraryFile (id_local INTEGER PRIMARY KEY, baseName TEXT, extension TEXT, folder INTEGER);
            CREATE TABLE Adobe_images (id_local INTEGER PRIMARY KEY, rootFile INTEGER, rating REAL, pick REAL, colorLabels TEXT);
            CREATE TABLE Adobe_imageDevelopSettings (image INTEGER, text TEXT);
            CREATE TABLE Adobe_libraryImageDevelopHistoryStep (id_local INTEGER PRIMARY KEY, image INTEGER, name TEXT);
            INSERT INTO AgLibraryFolder VALUES (1, 'Fotos/'), (2, 'Kirche/');
            INSERT INTO AgLibraryFile VALUES (10, 'A-0001', 'CR2', 1), (11, 'A-0002', 'CR2', 1),
                                             (12, 'IMG_1', 'CR2', 1), (13, 'IMG_1', 'CR2', 2);
            INSERT INTO Adobe_images VALUES (100, 10, 4, 1, 'Grün'), (101, 11, 0, 0, ''),
                                            (102, 12, NULL, -1, NULL), (103, 13, NULL, 0, NULL);
            INSERT INTO Adobe_imageDevelopSettings VALUES
                (100, 's = { Exposure2012 = 0.5, Temperature = 5000, }'),
                (101, 's = { Exposure2012 = 0, Temperature = 5000, }'),
                (102, 's = { Exposure2012 = 1, Temperature = 4000, }'),
                (103, 's = { Exposure2012 = 2, Temperature = 4000, }');
            INSERT INTO Adobe_libraryImageDevelopHistoryStep VALUES
                (1, 100, 'Importieren (1.1.19)'), (2, 100, 'Belichtung'),
                (3, 101, 'Importieren (1.1.19)'),
                (4, 102, 'Belichtung'), (5, 102, 'Einstellungen zurücksetzen'),
                (6, 103, 'Belichtung');
            "#,
        )
        .unwrap();
    }

    #[test]
    fn catalog_photos_are_found_by_name_and_folder() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("Hochzeit A.lrcat");
        fake_catalog(&path);
        let cat = Catalog::open(&path).unwrap();
        assert_eq!(cat.len(), 4);

        let a = cat.find(Path::new("E:/x/Fotos/A-0001.cr2")).unwrap();
        assert!(a.edited);
        assert_eq!(a.settings["Exposure2012"], Value::from(0.5));
        assert_eq!(a.decisions["rating"], Value::from(4));
        assert_eq!(a.decisions["pick_status"], Value::from(1));
        assert_eq!(a.decisions["color_label"], Value::from("grün"));

        // Only imported (maybe with an import preset): not the photographer's edit.
        assert!(!cat.find(Path::new("A-0002.CR2")).unwrap().edited);
        // Same name in two folders: the folder decides; reset photos are not edited.
        let reset = cat.find(Path::new("E:/x/Fotos/IMG_1.CR2")).unwrap();
        assert!(!reset.edited);
        assert_eq!(reset.decisions["pick_status"], Value::from(-1));
        assert!(cat.find(Path::new("E:/x/Kirche/IMG_1.CR2")).unwrap().edited);
        assert!(cat.find(Path::new("E:/x/Other/IMG_1.CR2")).is_none());
        assert!(cat.find(Path::new("missing.CR2")).is_none());

        // The catalog file is left as it was (immutable: no journal next to it).
        let names: Vec<_> = std::fs::read_dir(dir.path())
            .unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().to_string())
            .collect();
        assert_eq!(names, ["Hochzeit A.lrcat"]);
    }
}
