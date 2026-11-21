//! The colour temperature the camera *measured* for a photo, read from the RAW file.
//!
//! Canon cameras store their automatic white balance estimate for every frame — also when the
//! photographer shot with a fixed setting such as "Daylight". It tells how the light of this
//! frame differed from the frame before; shoot calibration uses it as one more feature for
//! temperature (see `calotype_inference_pipeline.shoot`). The as-shot value is no use for that:
//! with a fixed camera setting it is the same on every photo.
//!
//! Where it lives: MakerNotes tag `0x4001` ("ColorData", an array of 16-bit values whose first
//! entry is a version). CR2 files are TIFF (IFD0 → Exif IFD → MakerNote); CR3 files keep the
//! MakerNotes in the `CMT3` box or, on newer bodies, in the timed metadata track (`CTMD`,
//! one sample near the end of the file). Other makers and DNG: not read yet (`None`).

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

/// Bytes read from the start of the file: IFDs of a CR2, the `moov` box of a CR3.
const HEAD_BYTES: u64 = 1 << 20;
/// A CTMD sample is ~120 KiB; anything far larger is not what we are looking for.
const MAX_SAMPLE_BYTES: u64 = 4 << 20;
const TAG_EXIF_IFD: u16 = 0x8769;
const TAG_MAKER_NOTE: u16 = 0x927c;
const TAG_COLOR_DATA: u16 = 0x4001;

/// The camera's measured colour temperature in Kelvin, if the file carries one we can read.
pub fn measured_kelvin(path: &Path) -> Option<u32> {
    let mut file = File::open(path).ok()?;
    let mut head = Vec::new();
    file.by_ref().take(HEAD_BYTES).read_to_end(&mut head).ok()?;
    if let Some(kelvin) = from_head(&head) {
        return Some(kelvin);
    }
    // CR3 with the MakerNotes in the timed metadata track: one more small read.
    let (offset, size) = ctmd_sample(&head)?;
    if size == 0 || size > MAX_SAMPLE_BYTES {
        return None;
    }
    file.seek(SeekFrom::Start(offset)).ok()?;
    let mut sample = vec![0u8; usize::try_from(size).ok()?];
    file.read_exact(&mut sample).ok()?;
    from_ctmd(&sample)
}

/// From the bytes at the start of the file: CR2 (TIFF) or a CR3 with a `CMT3` box that has
/// the colour data.
fn from_head(head: &[u8]) -> Option<u32> {
    if let Some(tiff) = Tiff::new(head) {
        let exif = tiff.u32(tiff.entry(tiff.u32(4)? as usize, TAG_EXIF_IFD)? + 8)? as usize;
        let maker = tiff.u32(tiff.entry(exif, TAG_MAKER_NOTE)? + 8)? as usize;
        return kelvin(&tiff.shorts(maker, TAG_COLOR_DATA)?);
    }
    if head.get(4..8) == Some(b"ftyp") {
        let pos = head.windows(4).position(|w| w == b"CMT3")?;
        let tiff = Tiff::new(&head[pos + 4..])?;
        return kelvin(&tiff.shorts(tiff.u32(4)? as usize, TAG_COLOR_DATA)?);
    }
    None
}

/// Version-dependent position of `ColorTempMeasured` in Canon's ColorData (after ExifTool's
/// Canon tables; 13 and 48 checked against ExifTool on real 5D Mark IV / R6 Mark II files).
fn measured_index(version: u16) -> Option<usize> {
    match version {
        2..=7 | 9 | 10..=15 => Some(77),
        16..=19 => Some(85),
        32 | 33 => Some(99),
        34 | 48 => Some(119),
        _ => None,
    }
}

/// The measured temperature from a ColorData array — only when it looks like one: the four
/// values before it are the RGGB levels of the same measurement (equal greens, sane range).
fn kelvin(data: &[u16]) -> Option<u32> {
    let index = measured_index(*data.first()?)?;
    let levels = data.get(index - 4..index)?;
    let value = u32::from(*data.get(index)?);
    let sane_levels = levels[1] == levels[2]
        && levels[1] > 0
        && levels.iter().all(|&v| (64..=16384).contains(&v));
    ((1500..=20000).contains(&value) && sane_levels).then_some(value)
}

/// A TIFF structure (byte order + bounds-checked reads).
struct Tiff<'a> {
    bytes: &'a [u8],
    little: bool,
}

impl<'a> Tiff<'a> {
    fn new(bytes: &'a [u8]) -> Option<Self> {
        let little = match bytes.get(0..4)? {
            [b'I', b'I', 42, 0] => true,
            [b'M', b'M', 0, 42] => false,
            _ => return None,
        };
        Some(Self { bytes, little })
    }

    fn u16(&self, at: usize) -> Option<u16> {
        let b = self.bytes.get(at..at.checked_add(2)?)?;
        Some(if self.little {
            u16::from_le_bytes([b[0], b[1]])
        } else {
            u16::from_be_bytes([b[0], b[1]])
        })
    }

    fn u32(&self, at: usize) -> Option<u32> {
        let b = self.bytes.get(at..at.checked_add(4)?)?;
        let b = [b[0], b[1], b[2], b[3]];
        Some(if self.little {
            u32::from_le_bytes(b)
        } else {
            u32::from_be_bytes(b)
        })
    }

    /// Position of the entry with `tag` in the IFD at `ifd`.
    fn entry(&self, ifd: usize, tag: u16) -> Option<usize> {
        let count = usize::from(self.u16(ifd)?).min(1024);
        (0..count)
            .map(|i| ifd + 2 + i * 12)
            .find(|&entry| self.u16(entry) == Some(tag))
    }

    /// The 16-bit values of the entry with `tag` in the IFD at `ifd`.
    fn shorts(&self, ifd: usize, tag: u16) -> Option<Vec<u16>> {
        let entry = self.entry(ifd, tag)?;
        let count = (self.u32(entry + 4)? as usize).min(8192);
        let start = self.u32(entry + 8)? as usize;
        (0..count).map(|i| self.u16(start + 2 * i)).collect()
    }
}

/// Child boxes of an ISO base media box: (type, payload start, payload end).
fn boxes(bytes: &[u8], start: usize, end: usize) -> Vec<([u8; 4], usize, usize)> {
    let mut out = Vec::new();
    let mut at = start;
    while at + 8 <= end.min(bytes.len()) {
        let mut size = u64::from(u32::from_be_bytes([
            bytes[at],
            bytes[at + 1],
            bytes[at + 2],
            bytes[at + 3],
        ]));
        let kind = [bytes[at + 4], bytes[at + 5], bytes[at + 6], bytes[at + 7]];
        let mut header = 8usize;
        if size == 1 {
            let Some(b) = bytes.get(at + 8..at + 16) else {
                break;
            };
            size = u64::from_be_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]]);
            header = 16;
        }
        let Ok(size) = usize::try_from(size) else {
            break;
        };
        if size < header {
            break;
        }
        out.push((kind, at + header, at.saturating_add(size).min(end)));
        at = at.saturating_add(size);
    }
    out
}

fn child(bytes: &[u8], start: usize, end: usize, kind: &[u8; 4]) -> Option<(usize, usize)> {
    boxes(bytes, start, end)
        .into_iter()
        .find(|(k, _, _)| k == kind)
        .map(|(_, s, e)| (s, e))
}

fn be_u32(bytes: &[u8], at: usize) -> Option<u32> {
    let b = bytes.get(at..at.checked_add(4)?)?;
    Some(u32::from_be_bytes([b[0], b[1], b[2], b[3]]))
}

fn be_u64(bytes: &[u8], at: usize) -> Option<u64> {
    let b = bytes.get(at..at.checked_add(8)?)?;
    Some(u64::from_be_bytes([
        b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
    ]))
}

/// File offset and size of the first sample of the CR3's `CTMD` track.
fn ctmd_sample(head: &[u8]) -> Option<(u64, u64)> {
    if head.get(4..8) != Some(b"ftyp") {
        return None;
    }
    let (moov_start, moov_end) = child(head, 0, head.len(), b"moov")?;
    for (kind, start, end) in boxes(head, moov_start, moov_end) {
        if &kind != b"trak" {
            continue;
        }
        let table = child(head, start, end, b"mdia")
            .and_then(|(s, e)| child(head, s, e, b"minf"))
            .and_then(|(s, e)| child(head, s, e, b"stbl"));
        let Some((table_start, table_end)) = table else {
            continue;
        };
        let Some((stsd, _)) = child(head, table_start, table_end, b"stsd") else {
            continue;
        };
        if head.get(stsd + 12..stsd + 16) != Some(b"CTMD") {
            continue;
        }
        let (co64, _) = child(head, table_start, table_end, b"co64")?;
        let (stsz, _) = child(head, table_start, table_end, b"stsz")?;
        let offset = be_u64(head, co64 + 8)?;
        let uniform = u64::from(be_u32(head, stsz + 4)?);
        let size = if uniform > 0 {
            uniform
        } else {
            u64::from(be_u32(head, stsz + 12)?)
        };
        return Some((offset, size));
    }
    None
}

/// The measured temperature from a CTMD sample: records of type 7–9 hold TIFF blocks; the one
/// tagged as MakerNote carries the colour data.
fn from_ctmd(sample: &[u8]) -> Option<u32> {
    let le_u32 = |at: usize| {
        sample
            .get(at..at.checked_add(4)?)
            .map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]) as usize)
    };
    let mut record = 0usize;
    while record + 12 <= sample.len() {
        let size = le_u32(record)?;
        let kind = u16::from_le_bytes([sample[record + 4], sample[record + 5]]);
        if size < 12 {
            break;
        }
        let end = record.saturating_add(size).min(sample.len());
        if (7..=9).contains(&kind) {
            let mut entry = record + 12;
            while entry + 8 <= end {
                let entry_size = le_u32(entry)?;
                if entry_size < 8 {
                    break;
                }
                let entry_end = entry.saturating_add(entry_size).min(end);
                if let Some(tiff) = Tiff::new(&sample[entry + 8..entry_end]) {
                    let found = tiff
                        .u32(4)
                        .and_then(|ifd| tiff.shorts(ifd as usize, TAG_COLOR_DATA))
                        .and_then(|data| kelvin(&data));
                    if found.is_some() {
                        return found;
                    }
                }
                entry = entry_end;
            }
        }
        record = end;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    /// ColorData with `version`, the measured RGGB levels and `kelvin` at `index`.
    fn color_data(version: u16, index: usize, kelvin: u16) -> Vec<u16> {
        let mut data = vec![0u16; index + 40];
        data[0] = version;
        data[index - 4..index].copy_from_slice(&[2044, 1024, 1024, 1504]);
        data[index] = kelvin;
        data
    }

    /// A little-endian TIFF whose IFD at offset 8 has one SHORT-array entry.
    fn tiff_with(tag: u16, data: &[u16]) -> Vec<u8> {
        let mut t = b"II*\0".to_vec();
        t.extend(8u32.to_le_bytes());
        t.extend(1u16.to_le_bytes());
        t.extend(tag.to_le_bytes());
        t.extend(3u16.to_le_bytes());
        t.extend((data.len() as u32).to_le_bytes());
        t.extend(26u32.to_le_bytes()); // values right after the IFD (8 + 2 + 12 + 4)
        t.extend(0u32.to_le_bytes());
        for v in data {
            t.extend(v.to_le_bytes());
        }
        t
    }

    fn atom(kind: &[u8; 4], payload: &[u8]) -> Vec<u8> {
        let mut b = ((payload.len() + 8) as u32).to_be_bytes().to_vec();
        b.extend(kind);
        b.extend(payload);
        b
    }

    #[test]
    fn reads_the_measured_temperature_per_color_data_version() {
        for (version, index) in [(13u16, 77usize), (18, 85), (33, 99), (48, 119)] {
            assert_eq!(kelvin(&color_data(version, index, 5574)), Some(5574));
        }
        assert_eq!(kelvin(&color_data(99, 119, 5574)), None); // unknown version
    }

    #[test]
    fn rejects_values_that_do_not_look_like_a_measurement() {
        assert_eq!(kelvin(&color_data(48, 119, 900)), None);
        let mut odd = color_data(48, 119, 5574);
        odd[116] = 7; // greens differ: not RGGB levels
        assert_eq!(kelvin(&odd), None);
        assert_eq!(kelvin(&[48, 1, 2]), None); // too short
        assert_eq!(kelvin(&[]), None);
    }

    #[test]
    fn cr2_follows_exif_and_makernote() {
        // IFD0 (Exif pointer) → Exif IFD (MakerNote pointer) → Canon IFD with ColorData.
        let data = color_data(13, 77, 7406);
        let mut t = b"II*\0".to_vec();
        t.extend(8u32.to_le_bytes());
        let ifd = |tag: u16, kind: u16, count: u32, value: u32| {
            let mut e = 1u16.to_le_bytes().to_vec();
            e.extend(tag.to_le_bytes());
            e.extend(kind.to_le_bytes());
            e.extend(count.to_le_bytes());
            e.extend(value.to_le_bytes());
            e.extend(0u32.to_le_bytes());
            e
        };
        t.extend(ifd(TAG_EXIF_IFD, 4, 1, 26)); // IFD0 at 8, 18 bytes
        t.extend(ifd(TAG_MAKER_NOTE, 7, 4, 44)); // Exif IFD at 26
        t.extend(ifd(TAG_COLOR_DATA, 3, data.len() as u32, 62)); // Canon IFD at 44
        for v in &data {
            t.extend(v.to_le_bytes());
        }
        assert_eq!(from_head(&t), Some(7406));
        assert_eq!(from_head(&t[..60]), None); // cut off: no panic, no value
    }

    #[test]
    fn cr3_reads_the_metadata_track_sample() {
        let tiff = tiff_with(TAG_COLOR_DATA, &color_data(48, 119, 5574));
        let mut entry = ((tiff.len() + 8) as u32).to_le_bytes().to_vec();
        entry.extend(0x927cu32.to_le_bytes());
        entry.extend(&tiff);
        let mut sample = ((entry.len() + 12) as u32).to_le_bytes().to_vec();
        sample.extend(8u16.to_le_bytes());
        sample.extend([0u8; 6]);
        sample.extend(&entry);
        assert_eq!(from_ctmd(&sample), Some(5574));
        assert_eq!(from_ctmd(&sample[..40]), None);

        let mut stsd = vec![0u8; 8];
        stsd.extend(0u32.to_be_bytes());
        stsd.extend(b"CTMD");
        let mut co64 = vec![0u8; 8];
        co64.extend(123_456u64.to_be_bytes());
        let mut stsz = vec![0u8; 4];
        stsz.extend((sample.len() as u32).to_be_bytes());
        stsz.extend(1u32.to_be_bytes());
        let stbl = [
            atom(b"stsd", &stsd),
            atom(b"co64", &co64),
            atom(b"stsz", &stsz),
        ]
        .concat();
        let trak = atom(
            b"trak",
            &atom(b"mdia", &atom(b"minf", &atom(b"stbl", &stbl))),
        );
        let head = [atom(b"ftyp", b"crx isom"), atom(b"moov", &trak)].concat();
        assert_eq!(ctmd_sample(&head), Some((123_456, sample.len() as u64)));
        assert_eq!(ctmd_sample(b"II*\0"), None);
    }

    #[test]
    fn other_files_give_none() {
        assert_eq!(from_head(b""), None);
        assert_eq!(from_head(b"\xff\xd8\xff\xe0 JPEG"), None);
        assert_eq!(measured_kelvin(Path::new("does-not-exist.CR3")), None);
    }
}
