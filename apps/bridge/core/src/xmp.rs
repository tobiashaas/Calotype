//! Adobe Camera Raw XMP sidecars (`IMG_0001.CR3` → `IMG_0001.xmp`).
//!
//! - Reading: `crs:` develop settings of an edited photo become training targets, with the
//!   same key names Lightroom's SDK uses (`crs:Exposure2012` → `Exposure2012`).
//! - Writing: predicted settings go into a new sidecar, or update the `crs:` values of an
//!   existing one while keeping everything else (ratings, keywords, other tools' data).
//!
//! Lightroom, Camera Raw and Bridge read these sidecars when a RAW is imported.

use std::path::{Path, PathBuf};

use serde_json::{Map, Number, Value};

pub const CRS_NS: &str = "http://ns.adobe.com/camera-raw-settings/1.0/";
pub const LRFF_NS: &str = "https://github.com/tobiashaas/LR-FrameFlow/ns/1.0/";
/// Current Lightroom process version. Without it, Adobe treats the values as the 2003
/// process and the `*2012` sliders would be misread.
pub const PROCESS_VERSION: &str = "15.4";

/// `D:/Shoot/IMG_0001.CR3` → `D:/Shoot/IMG_0001.xmp` (Adobe's naming).
pub fn sidecar_path(raw: &Path) -> PathBuf {
    raw.with_extension("xmp")
}

/// Byte range of the attributes of the first (top-level) `rdf:Description` start tag.
///
/// Only these attributes are the photo's settings. Real sidecars (Lightroom, Camera Raw,
/// other tools) nest more `rdf:Description`s with their own `crs:` values — masks
/// (`MaskGroupBasedCorrections`), looks (`crs:Look` → `Parameters`), snapshots — e.g.
/// `crs:Exposure2012="0"` inside a mask. Reading those would overwrite the real values.
fn top_description(xmp: &str) -> Option<std::ops::Range<usize>> {
    let tag = "<rdf:Description";
    let start = xmp.find(tag)? + tag.len();
    let mut in_quotes = false;
    for (i, c) in xmp[start..].char_indices() {
        match c {
            '"' => in_quotes = !in_quotes,
            '>' if !in_quotes => return Some(start..start + i),
            _ => {}
        }
    }
    None
}

/// Top-level attributes only (see [`top_description`]); whole text if there is no tag.
fn top_attributes(xmp: &str) -> &str {
    top_description(xmp).map_or(xmp, |r| &xmp[r])
}

/// All simple top-level `crs:Name="value"` attributes. Numbers ("+21", "0.00") become numbers.
pub fn read_develop_settings(xmp: &str) -> Map<String, Value> {
    let mut out = Map::new();
    for (name, value) in crs_attributes(top_attributes(xmp)) {
        out.entry(name.to_string())
            .or_insert_with(|| parse_value(&unescape(value)));
    }
    out
}

/// The photographer's decisions stored in a sidecar: `xmp:Rating` (0–5, −1 = rejected) and
/// `xmp:Label`, as `{rating, pick_status, color_label}` like the Lightroom plugin sends them.
/// Lightroom keeps pick/reject flags in the catalog only, so a rejected flag appears here
/// only when another tool (e.g. Adobe Bridge) wrote rating −1.
pub fn read_decisions(xmp: &str) -> Map<String, Value> {
    let mut out = Map::new();
    for (name, value) in prefixed_attributes(top_attributes(xmp), "xmp:") {
        match name {
            "Rating" => match value.trim().parse::<i64>() {
                Ok(-1) => {
                    out.insert("pick_status".into(), Value::from(-1));
                }
                Ok(r @ 0..=5) => {
                    out.insert("rating".into(), Value::from(r));
                }
                _ => {}
            },
            "Label" => {
                let label = unescape(value).trim().to_lowercase();
                if !label.is_empty() && label != "none" {
                    out.insert("color_label".into(), Value::from(label));
                }
            }
            _ => {}
        }
    }
    out
}

/// True if the sidecar holds actual develop settings (not just ratings/keywords).
pub fn has_develop_settings(settings: &Map<String, Value>) -> bool {
    [
        "Exposure2012",
        "Temperature",
        "IncrementalTemperature",
        "Contrast2012",
    ]
    .iter()
    .any(|k| settings.contains_key(*k))
}

fn parse_value(raw: &str) -> Value {
    let trimmed = raw.trim();
    let numeric = trimmed.strip_prefix('+').unwrap_or(trimmed);
    if let Ok(i) = numeric.parse::<i64>() {
        return Value::Number(i.into());
    }
    if let Ok(f) = numeric.parse::<f64>() {
        if let Some(n) = Number::from_f64(f) {
            return Value::Number(n);
        }
    }
    Value::String(raw.to_string())
}

fn crs_attributes(xmp: &str) -> impl Iterator<Item = (&str, &str)> {
    prefixed_attributes(xmp, "crs:")
}

/// Iterate `prefix:Name="value"` pairs (attribute form, as Adobe writes simple values).
fn prefixed_attributes<'a>(
    xmp: &'a str,
    prefix: &'static str,
) -> impl Iterator<Item = (&'a str, &'a str)> {
    let mut rest = xmp;
    std::iter::from_fn(move || loop {
        let start = rest.find(prefix)?;
        let after = &rest[start + prefix.len()..];
        let name_len = after
            .find(|c: char| !c.is_ascii_alphanumeric() && c != '_')
            .unwrap_or(after.len());
        let name = &after[..name_len];
        let tail = &after[name_len..];
        rest = tail;
        if name.is_empty() {
            continue;
        }
        // Only `crs:Name="…"` (skips element form `<crs:ToneCurve>` and prefixes in values).
        let Some(value_part) = tail.strip_prefix("=\"") else {
            continue;
        };
        let end = value_part.find('"')?;
        rest = &value_part[end + 1..];
        return Some((name, &value_part[..end]));
    })
}

fn escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('"', "&quot;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn unescape(s: &str) -> String {
    s.replace("&quot;", "\"")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
}

/// Adobe-style number formatting: sign on sliders, two decimals for exposure.
fn format_value(key: &str, value: &Value) -> String {
    match value {
        Value::Number(n) => {
            let f = n.as_f64().unwrap_or_default();
            if key == "Exposure2012" {
                format!("{f:+.2}")
            } else if key == "Temperature" {
                format!("{}", f.round() as i64)
            } else if f.fract() == 0.0 {
                let i = f as i64;
                if i > 0 {
                    format!("+{i}")
                } else {
                    format!("{i}")
                }
            } else {
                format!("{f:+}")
            }
        }
        Value::String(s) => s.clone(),
        Value::Bool(b) => {
            if *b {
                "True".into()
            } else {
                "False".into()
            }
        }
        other => other.to_string(),
    }
}

/// Settings plus the attributes Lightroom needs to apply them.
fn with_required(settings: &Map<String, Value>) -> Vec<(String, String)> {
    let mut attrs: Vec<(String, String)> = settings
        .iter()
        .map(|(k, v)| (k.clone(), format_value(k, v)))
        .collect();
    let has = |k: &str| settings.contains_key(k);
    if has("Temperature") || has("Tint") || has("IncrementalTemperature") || has("IncrementalTint")
    {
        attrs.push(("WhiteBalance".into(), "Custom".into()));
    }
    attrs.push(("ProcessVersion".into(), PROCESS_VERSION.into()));
    attrs.push(("HasSettings".into(), "True".into()));
    attrs.sort();
    attrs.dedup_by(|a, b| a.0 == b.0);
    attrs
}

/// A complete new sidecar for a RAW that has none.
pub fn new_sidecar(settings: &Map<String, Value>, profile: &str) -> String {
    let mut out = String::new();
    out.push_str("<?xpacket begin=\"\u{feff}\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n");
    out.push_str("<x:xmpmeta xmlns:x=\"adobe:ns:meta/\" x:xmptk=\"LR-FrameFlow\">\n");
    out.push_str(" <rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\n");
    out.push_str("  <rdf:Description rdf:about=\"\"\n");
    out.push_str(&format!("    xmlns:crs=\"{CRS_NS}\"\n"));
    out.push_str(&format!("    xmlns:lrff=\"{LRFF_NS}\"\n"));
    out.push_str(&format!("    lrff:Profile=\"{}\"\n", escape(profile)));
    for (k, v) in with_required(settings) {
        out.push_str(&format!("    crs:{k}=\"{}\"\n", escape(&v)));
    }
    out.push_str("   />\n");
    out.push_str(" </rdf:RDF>\n");
    out.push_str("</x:xmpmeta>\n");
    out.push_str("<?xpacket end=\"w\"?>\n");
    out
}

/// Update an existing sidecar: replace present `crs:` values, insert missing ones into the
/// first `rdf:Description`. Everything else stays byte-for-byte.
pub fn update_sidecar(
    existing: &str,
    settings: &Map<String, Value>,
    profile: &str,
) -> Option<String> {
    let mut xmp = existing.to_string();
    let mut missing = Vec::new();
    for (k, v) in with_required(settings) {
        // Only the top-level tag: the same key inside a mask or look must stay untouched.
        // (Recomputed each time; replacements change the length.)
        let top = top_description(&xmp)?;
        let needle = format!("crs:{k}=\"");
        let found = xmp[top.clone()].find(&needle).map(|rel| top.start + rel);
        if let Some(pos) = found {
            let value_start = pos + needle.len();
            let value_end = value_start + xmp[value_start..].find('"')?;
            xmp.replace_range(value_start..value_end, &escape(&v));
        } else {
            missing.push(format!("crs:{k}=\"{}\"", escape(&v)));
        }
    }
    let marker = format!("lrff:Profile=\"{}\"", escape(profile));
    let has_lrff_ns = xmp.contains(LRFF_NS);
    let has_crs_ns = xmp.contains(CRS_NS);
    let mut insert = Vec::new();
    if !has_crs_ns {
        insert.push(format!("xmlns:crs=\"{CRS_NS}\""));
    }
    if !has_lrff_ns {
        insert.push(format!("xmlns:lrff=\"{LRFF_NS}\""));
    }
    if let Some(pos) = xmp.find("lrff:Profile=\"") {
        let value_start = pos + "lrff:Profile=\"".len();
        let value_end = value_start + xmp[value_start..].find('"')?;
        xmp.replace_range(value_start..value_end, &escape(profile));
    } else {
        insert.push(marker);
    }
    insert.extend(missing);
    if !insert.is_empty() {
        let tag = "<rdf:Description";
        let pos = xmp.find(tag)? + tag.len();
        let joined: String = insert.iter().map(|a| format!("\n    {a}")).collect();
        xmp.insert_str(pos, &joined);
    }
    Some(xmp)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const ADOBE: &str = r#"<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    xmp:Rating="4"
    crs:ProcessVersion="15.4"
    crs:WhiteBalance="Custom"
    crs:Temperature="5950"
    crs:Tint="+5"
    crs:Exposure2012="0.00"
    crs:Vibrance="+21"
    crs:CameraProfile="Adobe Standard">
   <crs:ToneCurvePV2012>
    <rdf:Seq><rdf:li>0, 0</rdf:li></rdf:Seq>
   </crs:ToneCurvePV2012>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"#;

    #[test]
    fn reads_adobe_attributes_as_numbers_and_strings() {
        let s = read_develop_settings(ADOBE);
        assert_eq!(s["Temperature"], json!(5950));
        assert_eq!(s["Tint"], json!(5));
        assert_eq!(s["Exposure2012"], json!(0.0));
        assert_eq!(s["Vibrance"], json!(21));
        assert_eq!(s["CameraProfile"], json!("Adobe Standard"));
        assert!(
            !s.contains_key("ToneCurvePV2012"),
            "element form is skipped"
        );
        assert!(has_develop_settings(&s));
    }

    #[test]
    fn new_sidecar_roundtrips_and_sets_process_version() {
        let settings = json!({"Exposure2012": 0.35, "Temperature": 5600.0, "Contrast2012": -12.0})
            .as_object()
            .unwrap()
            .clone();
        let xmp = new_sidecar(&settings, "Wedding \"Warm\"");
        assert!(xmp.contains("crs:Exposure2012=\"+0.35\""));
        assert!(xmp.contains("crs:Contrast2012=\"-12\""));
        assert!(xmp.contains("crs:ProcessVersion=\"15.4\""));
        assert!(xmp.contains("crs:WhiteBalance=\"Custom\""));
        assert!(xmp.contains("lrff:Profile=\"Wedding &quot;Warm&quot;\""));
        let back = read_develop_settings(&xmp);
        assert_eq!(back["Exposure2012"], json!(0.35));
        assert_eq!(back["Temperature"], json!(5600));
    }

    #[test]
    fn update_keeps_foreign_data_and_replaces_values() {
        let settings = json!({"Exposure2012": -0.4, "Highlights2012": -30.0})
            .as_object()
            .unwrap()
            .clone();
        let xmp = update_sidecar(ADOBE, &settings, "Test").unwrap();
        assert!(xmp.contains("xmp:Rating=\"4\""), "rating kept");
        assert!(xmp.contains("<crs:ToneCurvePV2012>"), "tone curve kept");
        assert!(xmp.contains("crs:Exposure2012=\"-0.40\""));
        assert!(
            xmp.contains("crs:Highlights2012=\"-30\""),
            "missing key inserted"
        );
        assert!(xmp.contains("lrff:Profile=\"Test\""));
        assert_eq!(xmp.matches("crs:ProcessVersion=").count(), 1);
        let again = update_sidecar(&xmp, &settings, "Test 2").unwrap();
        assert_eq!(again.matches("lrff:Profile=").count(), 1);
        assert!(again.contains("lrff:Profile=\"Test 2\""));
        assert_eq!(read_develop_settings(&again)["Vibrance"], json!(21));
    }

    /// Shape of real sidecars from Lightroom/Camera Raw/culling tools: masks and looks
    /// nest their own `crs:` values, which must not leak into the photo's settings.
    const NESTED: &str = r#"<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    xmp:Rating="5"
    crs:ProcessVersion="15.4"
    crs:Exposure2012="0.05646324"
    crs:Temperature="5120">
   <crs:MaskGroupBasedCorrections>
    <rdf:Seq><rdf:li>
     <rdf:Description crs:LocalExposure2012="0.2" crs:Exposure2012="0" crs:Highlights2012="-40"
       xmp:Rating="1"/>
    </rdf:li></rdf:Seq>
   </crs:MaskGroupBasedCorrections>
   <crs:Look>
    <rdf:Description crs:Name="Adobe Color">
     <crs:Parameters>
      <rdf:Description crs:Version="15.2" crs:ProcessVersion="11.0" crs:Exposure2012="0"/>
     </crs:Parameters>
    </rdf:Description>
   </crs:Look>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"#;

    #[test]
    fn nested_masks_and_looks_do_not_leak_into_settings() {
        let s = read_develop_settings(NESTED);
        assert_eq!(s["Exposure2012"], json!(0.05646324));
        assert_eq!(s["ProcessVersion"], json!(15.4));
        assert!(
            !s.contains_key("Highlights2012"),
            "mask value must not count"
        );
        assert!(!s.contains_key("Version"), "look parameter must not count");
        assert_eq!(read_decisions(NESTED)["rating"], json!(5));
    }

    #[test]
    fn update_only_touches_the_top_level() {
        let settings = json!({"Exposure2012": 0.5, "Highlights2012": -10.0})
            .as_object()
            .unwrap()
            .clone();
        let xmp = update_sidecar(NESTED, &settings, "P").unwrap();
        let back = read_develop_settings(&xmp);
        assert_eq!(back["Exposure2012"], json!(0.5));
        assert_eq!(back["Highlights2012"], json!(-10));
        assert!(
            xmp.contains(r#"crs:Highlights2012="-40""#),
            "mask value untouched"
        );
        assert!(
            xmp.contains(r#"crs:ProcessVersion="11.0""#),
            "look untouched"
        );
        assert_eq!(xmp.matches(r#"crs:Exposure2012="0""#).count(), 2);
    }

    #[test]
    fn reads_rating_label_and_reject() {
        let d = read_decisions(ADOBE);
        assert_eq!(d["rating"], json!(4));
        let labelled = r#"<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="-1" xmp:Label="Green"/>"#;
        let d = read_decisions(labelled);
        assert_eq!(d["pick_status"], json!(-1));
        assert_eq!(d["color_label"], json!("green"));
        assert!(!d.contains_key("rating"));
        assert!(
            read_decisions("<x:xmpmeta/>").is_empty(),
            "x:xmpmeta is not xmp:"
        );
    }

    #[test]
    fn sidecar_path_uses_adobe_naming() {
        assert_eq!(
            sidecar_path(Path::new("D:/a/IMG_1.CR3")),
            PathBuf::from("D:/a/IMG_1.xmp")
        );
    }
}
