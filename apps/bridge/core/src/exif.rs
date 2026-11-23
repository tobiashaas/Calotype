//! The EXIF snapshot of a RAW file (`exif-snapshot-v1`) for folder mode, where no Lightroom
//! reads the metadata for us: capture time, the camera's exposure settings (ISO, shutter time,
//! f-number, exposure compensation) and the measured colour temperature. Shoot calibration uses
//! them as features; without them it silently falls back to the picture alone.
//!
//! Where the exposure settings live: the Exif IFD. TIFF-based RAWs (CR2, NEF, ARW, DNG …) point
//! to it from IFD0 (tag `0x8769`); CR3 keeps it as its own little TIFF in the `CMT2` box.

use std::fs::File;
use std::io::Read;
use std::path::Path;

use serde_json::{json, Map, Value};

use crate::whitebalance::Tiff;

/// Bytes read from the start of the file: IFDs of a TIFF RAW, the `moov` box of a CR3.
const HEAD_BYTES: u64 = 1 << 20;
const TAG_EXIF_IFD: u16 = 0x8769;
const TAG_EXPOSURE_TIME: u16 = 0x829a;
const TAG_F_NUMBER: u16 = 0x829d;
const TAG_ISO: u16 = 0x8827;
const TAG_EXPOSURE_BIAS: u16 = 0x9204;

/// The camera's exposure settings; `None` where the file does not say.
#[derive(Debug, Default, Clone, Copy, PartialEq)]
pub struct CameraExposure {
    pub iso: Option<f64>,
    /// Seconds.
    pub shutter_speed: Option<f64>,
    /// f-number.
    pub aperture: Option<f64>,
    /// EV.
    pub exposure_bias: Option<f64>,
}

/// The exposure settings of a RAW file (all `None` for files we cannot read).
pub fn camera_exposure(path: &Path) -> CameraExposure {
    let mut head = Vec::new();
    let read = File::open(path).and_then(|f| f.take(HEAD_BYTES).read_to_end(&mut head));
    if read.is_err() {
        return CameraExposure::default();
    }
    from_head(&head).unwrap_or_default()
}

/// The snapshot folder mode sends with a photo: only the keys the file has.
pub fn snapshot(path: &Path) -> Value {
    let exposure = camera_exposure(path);
    let mut map = Map::new();
    if let Some(time) = crate::preview::capture_time(path) {
        map.insert("date_time_original".into(), json!(time));
    }
    if let Some(kelvin) = crate::whitebalance::measured_kelvin(path) {
        map.insert("wb_measured_kelvin".into(), json!(kelvin));
    }
    for (key, value) in [
        ("iso", exposure.iso),
        ("shutter_speed", exposure.shutter_speed),
        ("aperture", exposure.aperture),
        ("exposure_bias", exposure.exposure_bias),
    ] {
        if let Some(v) = value {
            map.insert(key.into(), json!(v));
        }
    }
    Value::Object(map)
}

fn from_head(head: &[u8]) -> Option<CameraExposure> {
    if let Some(tiff) = Tiff::new(head) {
        let exif = tiff.u32(tiff.entry(tiff.u32(4)? as usize, TAG_EXIF_IFD)? + 8)? as usize;
        return Some(read_ifd(&tiff, exif));
    }
    if head.get(4..8) == Some(b"ftyp") {
        let pos = head.windows(4).position(|w| w == b"CMT2")?;
        let tiff = Tiff::new(&head[pos + 4..])?;
        return Some(read_ifd(&tiff, tiff.u32(4)? as usize));
    }
    None
}

fn read_ifd(tiff: &Tiff, ifd: usize) -> CameraExposure {
    let positive = |v: Option<f64>| v.filter(|x| x.is_finite() && *x > 0.0);
    CameraExposure {
        iso: positive(integer(tiff, ifd, TAG_ISO)),
        shutter_speed: positive(rational(tiff, ifd, TAG_EXPOSURE_TIME, false)),
        aperture: positive(rational(tiff, ifd, TAG_F_NUMBER, false)),
        exposure_bias: rational(tiff, ifd, TAG_EXPOSURE_BIAS, true).filter(|x| x.is_finite()),
    }
}

/// A SHORT or LONG value stored in the entry itself.
fn integer(tiff: &Tiff, ifd: usize, tag: u16) -> Option<f64> {
    let entry = tiff.entry(ifd, tag)?;
    match tiff.u16(entry + 2)? {
        3 => Some(f64::from(tiff.u16(entry + 8)?)),
        4 => Some(f64::from(tiff.u32(entry + 8)?)),
        _ => None,
    }
}

/// A RATIONAL (or, `signed`, SRATIONAL) value: numerator / denominator at the entry's offset.
fn rational(tiff: &Tiff, ifd: usize, tag: u16, signed: bool) -> Option<f64> {
    let entry = tiff.entry(ifd, tag)?;
    let kind = tiff.u16(entry + 2)?;
    if kind != if signed { 10 } else { 5 } {
        return None;
    }
    let at = tiff.u32(entry + 8)? as usize;
    let (num, den) = (tiff.u32(at)?, tiff.u32(at.checked_add(4)?)?);
    if den == 0 {
        return None;
    }
    Some(if signed {
        f64::from(num as i32) / f64::from(den as i32)
    } else {
        f64::from(num) / f64::from(den)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A little-endian TIFF: IFD0 at 8 pointing to an Exif IFD with ISO, time, f-number, bias.
    fn tiff_raw() -> Vec<u8> {
        let entry = |tag: u16, kind: u16, value: u32| {
            let mut e = tag.to_le_bytes().to_vec();
            e.extend(kind.to_le_bytes());
            e.extend(1u32.to_le_bytes());
            e.extend(value.to_le_bytes());
            e
        };
        let mut t = b"II*\0".to_vec();
        t.extend(8u32.to_le_bytes());
        // IFD0 at 8: one entry (18 bytes incl. next-IFD pointer) → Exif IFD at 26.
        t.extend(1u16.to_le_bytes());
        t.extend(entry(TAG_EXIF_IFD, 4, 26));
        t.extend(0u32.to_le_bytes());
        // Exif IFD at 26: four entries (2 + 48 + 4 = 54 bytes) → values from 80.
        t.extend(4u16.to_le_bytes());
        t.extend(entry(TAG_EXPOSURE_TIME, 5, 80));
        t.extend(entry(TAG_F_NUMBER, 5, 88));
        t.extend(entry(TAG_ISO, 3, 800));
        t.extend(entry(TAG_EXPOSURE_BIAS, 10, 96));
        t.extend(0u32.to_le_bytes());
        for (num, den) in [(1u32, 250u32), (28, 10), ((-1i32) as u32, 3)] {
            t.extend(num.to_le_bytes());
            t.extend(den.to_le_bytes());
        }
        t
    }

    #[test]
    fn reads_the_exposure_settings_of_a_tiff_raw() {
        let e = from_head(&tiff_raw()).unwrap();
        assert_eq!(e.iso, Some(800.0));
        assert_eq!(e.shutter_speed, Some(0.004));
        assert_eq!(e.aperture, Some(2.8));
        assert!((e.exposure_bias.unwrap() + 1.0 / 3.0).abs() < 1e-9);
    }

    #[test]
    fn reads_the_exif_box_of_a_cr3() {
        // CMT2 holds the Exif IFD directly as IFD0 of its own TIFF.
        let raw = tiff_raw();
        let mut exif = b"II*\0".to_vec();
        exif.extend(8u32.to_le_bytes());
        exif.extend(&raw[26..]);
        // Offsets inside the Exif IFD were relative to the old start: shift them by -18.
        let shift = |b: &mut Vec<u8>, at: usize| {
            let v = u32::from_le_bytes([b[at], b[at + 1], b[at + 2], b[at + 3]]) - 18;
            b[at..at + 4].copy_from_slice(&v.to_le_bytes());
        };
        for i in [0usize, 1, 3] {
            shift(&mut exif, 8 + 2 + i * 12 + 8);
        }
        let mut head = 16u32.to_be_bytes().to_vec();
        head.extend(b"ftypcrx isom");
        head.extend(((exif.len() + 8) as u32).to_be_bytes());
        head.extend(b"CMT2");
        head.extend(&exif);
        let e = from_head(&head).unwrap();
        assert_eq!(e.iso, Some(800.0));
        assert_eq!(e.aperture, Some(2.8));
    }

    #[test]
    fn other_or_cut_files_give_nothing() {
        assert_eq!(from_head(b""), None);
        assert_eq!(from_head(b"\xff\xd8\xff\xe0 JPEG"), None);
        let cut = from_head(&tiff_raw()[..60]).unwrap_or_default();
        assert_eq!(cut.aperture, None); // values beyond the cut: none, no panic
        assert_eq!(
            camera_exposure(Path::new("does-not-exist.CR3")),
            CameraExposure::default()
        );
        assert_eq!(snapshot(Path::new("does-not-exist.CR3")), json!({}));
    }
}
