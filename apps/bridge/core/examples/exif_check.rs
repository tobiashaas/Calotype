//! Compare the Bridge's EXIF snapshot (folder mode) with exiftool on real files, read-only:
//!
//!     cargo run -p calotype-bridge-core --example exif_check -- <file>...
//!
//! Needs `exiftool` on the PATH. Per file and key: ours | exiftool, `!` marks a mismatch.
//! Exits 1 when any value differs (a key one side lacks counts too).

use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;

/// Our key, exiftool's tag (`-n`: numbers, not text) and how close is "equal".
const KEYS: [(&str, &str, f64); 6] = [
    ("iso", "ISO", 0.5),
    ("shutter_speed", "ExposureTime", 1e-6),
    ("aperture", "FNumber", 0.01),
    ("exposure_bias", "ExposureCompensation", 0.01),
    ("date_time_original", "DateTimeOriginal", 0.0),
    ("wb_measured_kelvin", "ColorTempMeasured", 0.5),
];

fn exiftool(path: &Path) -> Value {
    let out = Command::new("exiftool")
        .args(["-j", "-n"])
        .args(KEYS.map(|(_, tag, _)| format!("-{tag}")))
        .arg(path)
        .output()
        .expect("exiftool on PATH");
    let list: Value = serde_json::from_slice(&out.stdout).unwrap_or(Value::Null);
    list.get(0).cloned().unwrap_or(Value::Null)
}

/// exiftool writes `2024:05:01 14:03:22`, we `2024-05-01T14:03:22`.
fn same(ours: &Value, theirs: &Value, tolerance: f64) -> bool {
    match (ours, theirs) {
        (Value::Null, Value::Null) => true,
        (Value::String(a), Value::String(b)) => {
            let b = b.get(..19).unwrap_or(b);
            a == &format!("{}-{}-{}T{}", &b[0..4], &b[5..7], &b[8..10], &b[11..])
        }
        (a, b) => match (a.as_f64(), b.as_f64()) {
            (Some(a), Some(b)) => (a - b).abs() <= tolerance,
            _ => false,
        },
    }
}

fn show(v: &Value) -> String {
    match v {
        Value::Null => "-".into(),
        Value::String(s) => s.clone(),
        Value::Number(n) => {
            let f = n.as_f64().unwrap_or_default();
            if f.fract() == 0.0 {
                format!("{f:.0}")
            } else {
                format!("{f:.4}")
            }
        }
        other => other.to_string(),
    }
}

fn main() {
    let files: Vec<PathBuf> = std::env::args_os().skip(1).map(PathBuf::from).collect();
    assert!(!files.is_empty(), "usage: exif_check <file>...");
    let mut mismatches = 0;
    for file in files {
        let ours = calotype_bridge_core::exif::snapshot(&file);
        let theirs = exiftool(&file);
        println!("{}", file.file_name().unwrap_or_default().to_string_lossy());
        for (key, tag, tolerance) in KEYS {
            let (a, b) = (&ours[key], &theirs[tag]);
            let ok = same(a, b, tolerance);
            if !ok {
                mismatches += 1;
            }
            println!(
                "  {} {key:<20} {:<22} | {}",
                if ok { " " } else { "!" },
                show(a),
                show(b)
            );
        }
    }
    println!("{mismatches} mismatches");
    std::process::exit(i32::from(mismatches > 0));
}
