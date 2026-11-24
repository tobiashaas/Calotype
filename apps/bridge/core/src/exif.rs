//! The EXIF snapshot of a RAW file (`exif-snapshot-v1`) for folder mode, where no Lightroom
//! reads the metadata for us: capture time, the camera's exposure settings (ISO, shutter time,
//! f-number, exposure compensation) and the measured colour temperature. Shoot calibration uses
//! them as features; without them it silently falls back to the picture alone.
//!
//! Where the exposure settings live: the Exif IFD. TIFF-based RAWs (CR2, NEF, ARW, DNG …) point
//! to it from IFD0 (tag `0x8769`); CR3 keeps it as its own little TIFF in the `CMT2` box. A DNG
//! Lightroom saved metadata into has its Exif IFD at the end of the file, behind the image data
//! (found on a drone DNG, 41 MB in): then only a window there is read, not the whole file.
//!
//! The capture time is the Exif `DateTimeOriginal`; IFD0's `DateTime` only when there is none —
//! a DNG Lightroom wrote (panorama, HDR merge) has its save time there, not the shutter's.
//! Checked against exiftool on real CR3, CR2 and DNG files (`examples/exif_check.rs`). Olympus
//! ORF and Panasonic RW2 are TIFF files with their own magic number and read the same way —
//! checked on synthetic files only, no real ones at hand.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
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
const TAG_DATE_TIME_ORIGINAL: u16 = 0x9003;
/// Bytes read where an Exif IFD lies beyond the head: the IFD and the values right behind it.
const WINDOW_BYTES: u64 = 64 << 10;

/// The camera's exposure settings and capture time; `None` where the file does not say.
#[derive(Debug, Default, Clone, PartialEq)]
pub struct CameraExposure {
    pub iso: Option<f64>,
    /// Seconds.
    pub shutter_speed: Option<f64>,
    /// f-number.
    pub aperture: Option<f64>,
    /// EV.
    pub exposure_bias: Option<f64>,
    /// Exif `DateTimeOriginal` as `YYYY-MM-DDTHH:MM:SS`.
    pub date_time_original: Option<String>,
}

/// The exposure settings of a RAW file (all `None` for files we cannot read).
pub fn camera_exposure(path: &Path) -> CameraExposure {
    let Ok(mut file) = File::open(path) else {
        return CameraExposure::default();
    };
    let mut head = Vec::new();
    if (&mut file).take(HEAD_BYTES).read_to_end(&mut head).is_err() {
        return CameraExposure::default();
    }
    let mut far = |offset: usize| {
        let mut window = Vec::new();
        file.seek(SeekFrom::Start(offset as u64)).ok()?;
        (&mut file)
            .take(WINDOW_BYTES)
            .read_to_end(&mut window)
            .ok()?;
        Some(window)
    };
    from_file(&head, &mut far).unwrap_or_default()
}

/// The snapshot folder mode sends with a photo: only the keys the file has.
pub fn snapshot(path: &Path) -> Value {
    let exposure = camera_exposure(path);
    let mut map = Map::new();
    let time = exposure
        .date_time_original
        .clone()
        .or_else(|| crate::preview::capture_time(path));
    if let Some(time) = time {
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

#[cfg(test)]
fn from_head(head: &[u8]) -> Option<CameraExposure> {
    from_file(head, &mut |_| None)
}

/// From the head of the file; `far(offset)` reads a window further in.
fn from_file(head: &[u8], far: &mut dyn FnMut(usize) -> Option<Vec<u8>>) -> Option<CameraExposure> {
    if let Some(tiff) = Tiff::new(head) {
        // IFD0, then the Exif IFD: each read through a window where it lies beyond what we have.
        let mut windows: Vec<(usize, Vec<u8>)> = Vec::new();
        let ifd0 = tiff.u32(4)? as usize;
        if tiff.u16(ifd0).is_none() {
            windows.push((ifd0, far(ifd0)?));
        }
        let exif = {
            let parts = Parts::of(tiff, &windows);
            parts.u32(parts.entry(ifd0, TAG_EXIF_IFD)? + 8)? as usize
        };
        if Parts::of(tiff, &windows).u16(exif).is_none() {
            windows.push((exif, far(exif)?));
        }
        return Some(read_ifd(&Parts::of(tiff, &windows), exif));
    }
    if head.get(4..8) == Some(b"ftyp") {
        let pos = head.windows(4).position(|w| w == b"CMT2")?;
        let tiff = Tiff::new(&head[pos + 4..])?;
        let ifd = tiff.u32(4)? as usize;
        return Some(read_ifd(&Parts(vec![tiff]), ifd));
    }
    None
}

/// The parts of a TIFF read so far — its head and windows further in — as one: a value is
/// read from whichever part holds it (a Lightroom-saved DNG keeps its IFDs at the end of the
/// file and their values near the start). Values in no part read as `None`.
struct Parts<'a>(Vec<Tiff<'a>>);

impl<'a> Parts<'a> {
    fn of(head: Tiff<'a>, windows: &'a [(usize, Vec<u8>)]) -> Self {
        let mut parts = vec![head];
        parts.extend(windows.iter().map(|(at, w)| head.window(w, *at)));
        Parts(parts)
    }

    fn u16(&self, at: usize) -> Option<u16> {
        self.0.iter().find_map(|t| t.u16(at))
    }

    fn u32(&self, at: usize) -> Option<u32> {
        self.0.iter().find_map(|t| t.u32(at))
    }

    fn bytes(&self, at: usize, len: usize) -> Option<&'a [u8]> {
        self.0.iter().find_map(|t| t.bytes(at, len))
    }

    /// Position of the entry with `tag` in the IFD at `ifd`.
    fn entry(&self, ifd: usize, tag: u16) -> Option<usize> {
        let count = usize::from(self.u16(ifd)?).min(1024);
        (0..count)
            .map(|i| ifd + 2 + i * 12)
            .find(|&entry| self.u16(entry) == Some(tag))
    }
}

fn read_ifd(tiff: &Parts, ifd: usize) -> CameraExposure {
    let positive = |v: Option<f64>| v.filter(|x| x.is_finite() && *x > 0.0);
    CameraExposure {
        iso: positive(integer(tiff, ifd, TAG_ISO)),
        shutter_speed: positive(rational(tiff, ifd, TAG_EXPOSURE_TIME, false)),
        aperture: positive(rational(tiff, ifd, TAG_F_NUMBER, false)),
        exposure_bias: rational(tiff, ifd, TAG_EXPOSURE_BIAS, true).filter(|x| x.is_finite()),
        date_time_original: date(tiff, ifd, TAG_DATE_TIME_ORIGINAL),
    }
}

/// An ASCII date (20 bytes incl. NUL, so stored at the entry's offset).
fn date(tiff: &Parts, ifd: usize, tag: u16) -> Option<String> {
    let entry = tiff.entry(ifd, tag)?;
    if tiff.u16(entry + 2)? != 2 || tiff.u32(entry + 4)? < 19 {
        return None;
    }
    crate::preview::exif_time(tiff.bytes(tiff.u32(entry + 8)? as usize, 19)?)
}

/// A SHORT or LONG value stored in the entry itself.
fn integer(tiff: &Parts, ifd: usize, tag: u16) -> Option<f64> {
    let entry = tiff.entry(ifd, tag)?;
    match tiff.u16(entry + 2)? {
        3 => Some(f64::from(tiff.u16(entry + 8)?)),
        4 => Some(f64::from(tiff.u32(entry + 8)?)),
        _ => None,
    }
}

/// A RATIONAL (or, `signed`, SRATIONAL) value: numerator / denominator at the entry's offset.
fn rational(tiff: &Parts, ifd: usize, tag: u16, signed: bool) -> Option<f64> {
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

    /// Laid out like a drone DNG Lightroom saved metadata into: IFD0 (with `DateTime`, the save
    /// time) and, just before it, the Exif IFD (with `DateTimeOriginal`, the shutter) lie at the
    /// end of the file, far behind the head; the Exif values stayed near the start.
    const FAR: usize = 4 << 20;
    fn dng_with_metadata_at_the_end() -> Vec<u8> {
        let entry = |tag: u16, kind: u16, count: u32, value: u32| {
            let mut e = tag.to_le_bytes().to_vec();
            e.extend(kind.to_le_bytes());
            e.extend(count.to_le_bytes());
            e.extend(value.to_le_bytes());
            e
        };
        let at = |offset: usize| (FAR + offset) as u32;
        let mut file = b"II*\0".to_vec();
        file.extend(at(100).to_le_bytes());
        // Exif values near the start: exposure time at 64, DateTimeOriginal at 72.
        file.resize(64, 0);
        file.extend(1u32.to_le_bytes());
        file.extend(1000u32.to_le_bytes());
        file.extend(b"2024:06:11 11:28:20\0");
        file.resize(FAR, 0); // image data
                             // Exif IFD at FAR: three entries.
        file.extend(3u16.to_le_bytes());
        file.extend(entry(TAG_EXPOSURE_TIME, 5, 1, 64));
        file.extend(entry(TAG_ISO, 3, 1, 110));
        file.extend(entry(TAG_DATE_TIME_ORIGINAL, 2, 20, 72));
        file.extend(0u32.to_le_bytes());
        // IFD0 at FAR + 100: DateTime + Exif pointer (2 + 24 + 4 = 30 bytes), its text at +130.
        file.resize(FAR + 100, 0);
        file.extend(2u16.to_le_bytes());
        file.extend(entry(0x0132, 2, 20, at(130)));
        file.extend(entry(TAG_EXIF_IFD, 4, 1, at(0)));
        file.extend(0u32.to_le_bytes());
        file.extend(b"2024:06:12 09:00:00\0");
        file
    }

    #[test]
    fn follows_ifds_beyond_the_head() {
        let file = dng_with_metadata_at_the_end();
        let head = &file[..HEAD_BYTES as usize];
        let mut asked = Vec::new();
        let e = from_file(head, &mut |offset| {
            asked.push(offset);
            let window = file.get(offset..)?;
            Some(window[..window.len().min(WINDOW_BYTES as usize)].to_vec())
        })
        .unwrap();
        assert_eq!(
            asked,
            [FAR + 100, FAR],
            "a window for IFD0, one for the Exif IFD"
        );
        assert_eq!(e.iso, Some(110.0));
        assert_eq!(e.shutter_speed, Some(0.001), "value read from the head");
        assert_eq!(e.date_time_original.as_deref(), Some("2024-06-11T11:28:20"));
        assert_eq!(
            from_head(head),
            None,
            "without the windows: nothing, no panic"
        );
    }

    #[test]
    fn the_capture_time_is_the_exif_original_not_the_save_time() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("drone.dng");
        std::fs::write(&path, dng_with_metadata_at_the_end()).unwrap();
        let snap = snapshot(&path);
        assert_eq!(snap["date_time_original"], "2024-06-11T11:28:20");
        assert_eq!(
            (snap["iso"].as_f64(), snap["shutter_speed"].as_f64()),
            (Some(110.0), Some(0.001))
        );
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
    fn reads_orf_and_rw2_like_tiff() {
        for magic in [*b"IIRO", *b"IIRS", *b"IIU\0"] {
            let mut raw = tiff_raw();
            raw[..4].copy_from_slice(&magic);
            let e = from_head(&raw).unwrap();
            assert_eq!((e.iso, e.aperture), (Some(800.0), Some(2.8)), "{magic:?}");
        }
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
