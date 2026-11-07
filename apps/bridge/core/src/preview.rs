//! Model input preview from the original file (ADR 004): the *unedited* image.
//!
//! - JPEG/TIFF/PNG: the file itself.
//! - RAW (CR2/CR3/NEF/ARW/RAF/DNG/…): the largest embedded camera JPEG. RAW containers
//!   carry one or more full JPEGs (thumbnail, preview, sometimes full size), so we scan
//!   for JPEG start markers and keep the candidate with the most pixels.
//!
//! Output is always an upright JPEG with the longest side ≤ [`MAX_EDGE`]. Cameras store
//! portrait shots sideways and only record the rotation in metadata, so the orientation
//! is applied here: from the RAW container (TIFF IFD0 for CR2/NEF/ARW/DNG, the `CMT1`
//! box for CR3), else from the JPEG's own EXIF.

use std::io::Cursor;
use std::path::Path;

use image::metadata::Orientation;
use image::{imageops::FilterType, DynamicImage, ImageDecoder, ImageFormat, ImageReader};
use thiserror::Error;

pub const MAX_EDGE: u32 = 1200;
/// Embedded thumbnails below this size are useless as model input.
pub const MIN_EDGE: u32 = 320;
const MAX_CANDIDATES: usize = 64;
const JPEG_QUALITY: u8 = 90;

/// Start of the message of [`PreviewError::Read`]; the outbox uses it to tell an unreachable
/// file from a server error.
pub const READ_ERROR_PREFIX: &str = "cannot read ";

#[derive(Debug, Error)]
pub enum PreviewError {
    #[error("cannot read {path}: {source}")]
    Read {
        path: String,
        source: std::io::Error,
    },
    #[error("cannot decode image: {0}")]
    Decode(String),
    #[error("no usable embedded preview (largest is {0}px, need {MIN_EDGE}px)")]
    TooSmall(u32),
    #[error("no embedded JPEG preview found")]
    NoEmbeddedJpeg,
}

const DIRECT_EXTENSIONS: &[&str] = &["jpg", "jpeg", "tif", "tiff", "png"];

pub fn build_preview(path: &Path) -> Result<Vec<u8>, PreviewError> {
    let bytes = std::fs::read(path).map_err(|source| PreviewError::Read {
        path: path.display().to_string(),
        source,
    })?;
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.to_ascii_lowercase())
        .unwrap_or_default();

    let (mut img, orientation) = if DIRECT_EXTENSIONS.contains(&ext.as_str()) {
        decode_oriented(&bytes, None)?
    } else {
        let (img, jpeg_orientation) = best_embedded_jpeg(&bytes)?;
        let orientation = raw_container_orientation(&bytes)
            .filter(|o| *o != Orientation::NoTransforms)
            .unwrap_or(jpeg_orientation);
        (img, orientation)
    };
    img.apply_orientation(orientation);
    encode(downscale(img))
}

fn decode_error(e: image::ImageError) -> PreviewError {
    PreviewError::Decode(e.to_string())
}

/// Decode and return the image together with its EXIF orientation.
fn decode_oriented(
    bytes: &[u8],
    format: Option<ImageFormat>,
) -> Result<(DynamicImage, Orientation), PreviewError> {
    let reader = match format {
        Some(f) => ImageReader::with_format(Cursor::new(bytes), f),
        None => ImageReader::new(Cursor::new(bytes))
            .with_guessed_format()
            .map_err(|e| PreviewError::Decode(e.to_string()))?,
    };
    let mut decoder = reader.into_decoder().map_err(decode_error)?;
    let orientation = decoder.orientation().unwrap_or(Orientation::NoTransforms);
    let img = DynamicImage::from_decoder(decoder).map_err(decode_error)?;
    Ok((img, orientation))
}

/// Orientation recorded by the RAW container, if we know where to look.
fn raw_container_orientation(bytes: &[u8]) -> Option<Orientation> {
    let tiff = if tiff_byte_order(bytes).is_some() {
        bytes // CR2, NEF, ARW, DNG, … are TIFF files
    } else if bytes.get(4..8) == Some(b"ftyp") {
        // CR3 (ISO base media): the `CMT1` box holds a TIFF IFD0 with the EXIF basics.
        let head = &bytes[..bytes.len().min(1 << 20)];
        let pos = head.windows(4).position(|w| w == b"CMT1")?;
        &bytes[pos + 4..]
    } else {
        return None;
    };
    Orientation::from_exif(tiff_orientation(tiff)?)
}

/// `Some(true)` for little-endian ("II*\0"), `Some(false)` for big-endian ("MM\0*").
fn tiff_byte_order(t: &[u8]) -> Option<bool> {
    match t.get(0..4)? {
        [b'I', b'I', 42, 0] => Some(true),
        [b'M', b'M', 0, 42] => Some(false),
        _ => None,
    }
}

/// Orientation tag (0x0112) from IFD0 of a TIFF structure.
fn tiff_orientation(t: &[u8]) -> Option<u8> {
    let le = tiff_byte_order(t)?;
    let u16_at = |o: usize| {
        t.get(o..o + 2).map(|b| {
            if le {
                u16::from_le_bytes([b[0], b[1]])
            } else {
                u16::from_be_bytes([b[0], b[1]])
            }
        })
    };
    let u32_at = |o: usize| {
        t.get(o..o + 4).map(|b| {
            let b = [b[0], b[1], b[2], b[3]];
            if le {
                u32::from_le_bytes(b)
            } else {
                u32::from_be_bytes(b)
            }
        })
    };
    let ifd = u32_at(4)? as usize;
    let entries = usize::from(u16_at(ifd)?);
    for i in 0..entries.min(512) {
        let entry = ifd + 2 + i * 12;
        if u16_at(entry)? == 0x0112 {
            return u8::try_from(u16_at(entry + 8)?).ok();
        }
    }
    None
}

/// Decode the best embedded JPEG (plus its own EXIF orientation): the smallest one that
/// still covers [`MAX_EDGE`], else the largest. RAWs often embed a full-size JPEG
/// (24+ MP) next to a ~1.6k preview; decoding the full one would cost seconds per photo.
pub fn best_embedded_jpeg(bytes: &[u8]) -> Result<(DynamicImage, Orientation), PreviewError> {
    // (pixels, longest edge, offset)
    let mut candidates: Vec<(u64, u32, usize)> = Vec::new();
    for offset in jpeg_start_offsets(bytes).take(MAX_CANDIDATES) {
        // Reading only the header is cheap; decoders stop at the end-of-image marker,
        // so trailing RAW data after the JPEG does not matter.
        let reader = ImageReader::with_format(Cursor::new(&bytes[offset..]), ImageFormat::Jpeg);
        if let Ok((w, h)) = reader.into_dimensions() {
            candidates.push((u64::from(w) * u64::from(h), w.max(h), offset));
        }
    }
    let covering = candidates
        .iter()
        .filter(|c| c.1 >= MAX_EDGE)
        .min_by_key(|c| c.0);
    let best = covering.or_else(|| candidates.iter().max_by_key(|c| c.0));
    let &(_, longest_edge, offset) = best.ok_or(PreviewError::NoEmbeddedJpeg)?;
    let (img, orientation) = if longest_edge >= 2 * MAX_EDGE {
        // Only a full-size JPEG (e.g. Canon CR2): decode at 1/2, 1/4 or 1/8 directly in the
        // DCT instead of building a 20+ MP image and shrinking it (~3x faster).
        let orientation = jpeg_orientation(&bytes[offset..]);
        (decode_jpeg_scaled(&bytes[offset..], MAX_EDGE)?, orientation)
    } else {
        decode_oriented(&bytes[offset..], Some(ImageFormat::Jpeg))?
    };
    let longest = img.width().max(img.height());
    if longest < MIN_EDGE {
        return Err(PreviewError::TooSmall(longest));
    }
    Ok((img, orientation))
}

/// EXIF orientation of a JPEG from its header only.
fn jpeg_orientation(jpeg: &[u8]) -> Orientation {
    ImageReader::with_format(Cursor::new(jpeg), ImageFormat::Jpeg)
        .into_decoder()
        .ok()
        .and_then(|mut d| d.orientation().ok())
        .unwrap_or(Orientation::NoTransforms)
}

/// Decode with DCT scaling to the smallest size whose longest edge is still ≥ `edge`.
fn decode_jpeg_scaled(jpeg: &[u8], edge: u32) -> Result<DynamicImage, PreviewError> {
    let err = |e: jpeg_decoder::Error| PreviewError::Decode(e.to_string());
    let mut decoder = jpeg_decoder::Decoder::new(Cursor::new(jpeg));
    decoder.read_info().map_err(err)?;
    let info = decoder
        .info()
        .ok_or_else(|| PreviewError::Decode("no JPEG header".into()))?;
    let (w, h) = (u32::from(info.width), u32::from(info.height));
    let ratio = f64::from(edge) / f64::from(w.max(h));
    let want = |v: u32| (f64::from(v) * ratio).ceil().clamp(1.0, 65535.0) as u16;
    let (sw, sh) = decoder.scale(want(w), want(h)).map_err(err)?;
    let pixels = decoder.decode().map_err(err)?;
    let (sw, sh) = (u32::from(sw), u32::from(sh));
    let info = decoder
        .info()
        .ok_or_else(|| PreviewError::Decode("no JPEG header".into()))?;
    match info.pixel_format {
        jpeg_decoder::PixelFormat::RGB24 => {
            image::RgbImage::from_raw(sw, sh, pixels).map(DynamicImage::ImageRgb8)
        }
        jpeg_decoder::PixelFormat::L8 => {
            image::GrayImage::from_raw(sw, sh, pixels).map(DynamicImage::ImageLuma8)
        }
        other => {
            return Err(PreviewError::Decode(format!(
                "unsupported JPEG pixel format {other:?}"
            )))
        }
    }
    .ok_or_else(|| PreviewError::Decode("JPEG size mismatch".into()))
}

/// Offsets of `FF D8 FF` (JPEG start-of-image followed by a marker).
fn jpeg_start_offsets(bytes: &[u8]) -> impl Iterator<Item = usize> + '_ {
    // Jump between 0xFF bytes instead of testing every 3-byte window.
    let mut pos = 0;
    std::iter::from_fn(move || {
        while let Some(i) = bytes.get(pos..)?.iter().position(|&b| b == 0xFF) {
            let at = pos + i;
            pos = at + 1;
            if bytes.get(at + 1..at + 3) == Some(&[0xD8, 0xFF]) {
                return Some(at);
            }
        }
        None
    })
}

fn downscale(img: DynamicImage) -> DynamicImage {
    if img.width().max(img.height()) > MAX_EDGE {
        img.resize(MAX_EDGE, MAX_EDGE, FilterType::Lanczos3)
    } else {
        img
    }
}

fn encode(img: DynamicImage) -> Result<Vec<u8>, PreviewError> {
    let rgb = img.to_rgb8();
    let mut out = Vec::new();
    let encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut out, JPEG_QUALITY);
    rgb.write_with_encoder(encoder)
        .map_err(|e| PreviewError::Decode(e.to_string()))?;
    Ok(out)
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use image::RgbImage;

    pub fn jpeg_bytes(w: u32, h: u32) -> Vec<u8> {
        let img = RgbImage::from_fn(w, h, |x, y| {
            image::Rgb([(x % 256) as u8, (y % 256) as u8, 90])
        });
        let mut out = Vec::new();
        img.write_to(&mut Cursor::new(&mut out), ImageFormat::Jpeg)
            .unwrap();
        out
    }

    fn dims(jpeg: &[u8]) -> (u32, u32) {
        let img = image::load_from_memory(jpeg).unwrap();
        (img.width(), img.height())
    }

    #[test]
    fn full_size_only_jpeg_is_decoded_scaled_and_stays_upright() {
        // CR2-like: only a large embedded JPEG plus a thumbnail, portrait via the container
        let mut cr2 = tiff_with_orientation(6);
        cr2.extend(jpeg_bytes(160, 120));
        cr2.extend(jpeg_bytes(5000, 3000));
        let (img, _) = best_embedded_jpeg(&cr2).unwrap();
        assert_eq!(
            (img.width(), img.height()),
            (1250, 750),
            "1/4 DCT scale, still ≥ 1200"
        );
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("a.cr2");
        std::fs::write(&path, cr2).unwrap();
        assert_eq!(dims(&build_preview(&path).unwrap()), (720, 1200));
    }

    #[test]
    fn picks_best_embedded_jpeg_from_raw_container() {
        let mut raw = b"FAKE-RAW-HEADER".to_vec();
        raw.extend(jpeg_bytes(160, 120)); // thumbnail
        raw.extend(vec![0x42; 4096]); // sensor data
        raw.extend(jpeg_bytes(1600, 1000)); // preview
        raw.extend(vec![0x17; 2048]);
        let (img, _) = best_embedded_jpeg(&raw).unwrap();
        assert_eq!((img.width(), img.height()), (1600, 1000));
    }

    #[test]
    fn prefers_smallest_jpeg_covering_max_edge_over_full_size() {
        let mut raw = b"FAKE".to_vec();
        raw.extend(jpeg_bytes(4000, 2667)); // full-size embedded JPEG
        raw.extend(jpeg_bytes(1620, 1080)); // preview, enough for 1200 px
        raw.extend(jpeg_bytes(160, 120)); // thumbnail
        let (img, _) = best_embedded_jpeg(&raw).unwrap();
        assert_eq!((img.width(), img.height()), (1620, 1080));
    }

    /// Minimal little-endian TIFF header + IFD0 with only the Orientation tag.
    fn tiff_with_orientation(value: u16) -> Vec<u8> {
        let mut t = b"II*\0".to_vec();
        t.extend(8u32.to_le_bytes()); // IFD0 offset
        t.extend(1u16.to_le_bytes()); // one entry
        t.extend(0x0112u16.to_le_bytes());
        t.extend(3u16.to_le_bytes()); // SHORT
        t.extend(1u32.to_le_bytes());
        t.extend(value.to_le_bytes());
        t.extend([0, 0]);
        t.extend(0u32.to_le_bytes()); // no next IFD
        t
    }

    #[test]
    fn reads_orientation_from_tiff_raw_and_cr3() {
        let mut nef = tiff_with_orientation(6);
        nef.extend(jpeg_bytes(1600, 1000));
        assert_eq!(raw_container_orientation(&nef), Some(Orientation::Rotate90));

        let mut cr3 = b"\0\0\0\x18ftypcrx \0\0\0\x01crx isom".to_vec();
        cr3.extend(b"\0\0\0\x30CMT1");
        cr3.extend(tiff_with_orientation(8));
        assert_eq!(
            raw_container_orientation(&cr3),
            Some(Orientation::Rotate270)
        );

        assert_eq!(raw_container_orientation(b"FUJIFILMCCD-RAW "), None);
    }

    #[test]
    fn portrait_raw_preview_is_upright() {
        let dir = tempfile::tempdir().unwrap();
        let raw = dir.path().join("portrait.nef");
        let mut bytes = tiff_with_orientation(6); // camera held upright, sensor sideways
        bytes.extend(jpeg_bytes(1600, 1000));
        std::fs::write(&raw, bytes).unwrap();
        assert_eq!(dims(&build_preview(&raw).unwrap()), (750, 1200));
    }

    #[test]
    fn rejects_raw_with_only_thumbnail() {
        let mut raw = vec![0u8; 100];
        raw.extend(jpeg_bytes(160, 120));
        assert!(matches!(
            best_embedded_jpeg(&raw),
            Err(PreviewError::TooSmall(160))
        ));
    }

    #[test]
    fn rejects_raw_without_jpeg() {
        assert!(matches!(
            best_embedded_jpeg(&[1, 2, 3, 0xFF, 0xD8]),
            Err(PreviewError::NoEmbeddedJpeg)
        ));
    }

    #[test]
    fn build_preview_downscales_jpeg_and_raw() {
        let dir = tempfile::tempdir().unwrap();
        let jpg = dir.path().join("a.JPG");
        std::fs::write(&jpg, jpeg_bytes(2400, 1600)).unwrap();
        assert_eq!(dims(&build_preview(&jpg).unwrap()), (1200, 800));

        let raw = dir.path().join("b.cr3");
        let mut bytes = vec![0u8; 64];
        bytes.extend(jpeg_bytes(1000, 1500));
        std::fs::write(&raw, bytes).unwrap();
        assert_eq!(dims(&build_preview(&raw).unwrap()), (800, 1200));
    }

    #[test]
    fn small_jpeg_is_kept_as_is() {
        let dir = tempfile::tempdir().unwrap();
        let jpg = dir.path().join("small.jpeg");
        std::fs::write(&jpg, jpeg_bytes(640, 480)).unwrap();
        assert_eq!(dims(&build_preview(&jpg).unwrap()), (640, 480));
    }

    #[test]
    fn missing_file_is_read_error() {
        assert!(matches!(
            build_preview(Path::new("does/not/exist.nef")),
            Err(PreviewError::Read { .. })
        ));
    }
}
