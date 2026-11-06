//! Model input preview from the original file (ADR 004): the *unedited* image.
//!
//! - JPEG/TIFF/PNG: the file itself.
//! - RAW (CR2/CR3/NEF/ARW/RAF/DNG/…): the largest embedded camera JPEG. RAW containers
//!   carry one or more full JPEGs (thumbnail, preview, sometimes full size), so we scan
//!   for JPEG start markers and keep the candidate with the most pixels.
//!
//! Output is always a JPEG with the longest side ≤ [`MAX_EDGE`].

use std::io::Cursor;
use std::path::Path;

use image::{imageops::FilterType, DynamicImage, ImageFormat, ImageReader};
use thiserror::Error;

pub const MAX_EDGE: u32 = 1200;
/// Embedded thumbnails below this size are useless as model input.
pub const MIN_EDGE: u32 = 320;
const MAX_CANDIDATES: usize = 64;
const JPEG_QUALITY: u8 = 90;

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

    let img = if DIRECT_EXTENSIONS.contains(&ext.as_str()) {
        image::load_from_memory(&bytes).map_err(|e| PreviewError::Decode(e.to_string()))?
    } else {
        largest_embedded_jpeg(&bytes)?
    };
    encode(img)
}

/// Decode the embedded JPEG with the most pixels.
pub fn largest_embedded_jpeg(bytes: &[u8]) -> Result<DynamicImage, PreviewError> {
    let mut best: Option<(u64, usize)> = None;
    for offset in jpeg_start_offsets(bytes).take(MAX_CANDIDATES) {
        // Reading only the header is cheap; decoders stop at the end-of-image marker,
        // so trailing RAW data after the JPEG does not matter.
        let reader = ImageReader::with_format(Cursor::new(&bytes[offset..]), ImageFormat::Jpeg);
        if let Ok((w, h)) = reader.into_dimensions() {
            let pixels = u64::from(w) * u64::from(h);
            if best.is_none_or(|(p, _)| pixels > p) {
                best = Some((pixels, offset));
            }
        }
    }
    let (_, offset) = best.ok_or(PreviewError::NoEmbeddedJpeg)?;
    let img = image::load_from_memory_with_format(&bytes[offset..], ImageFormat::Jpeg)
        .map_err(|e| PreviewError::Decode(e.to_string()))?;
    let longest = img.width().max(img.height());
    if longest < MIN_EDGE {
        return Err(PreviewError::TooSmall(longest));
    }
    Ok(img)
}

/// Offsets of `FF D8 FF` (JPEG start-of-image followed by a marker).
fn jpeg_start_offsets(bytes: &[u8]) -> impl Iterator<Item = usize> + '_ {
    bytes
        .windows(3)
        .enumerate()
        .filter(|(_, w)| w == &[0xFF, 0xD8, 0xFF])
        .map(|(i, _)| i)
}

fn encode(img: DynamicImage) -> Result<Vec<u8>, PreviewError> {
    let img = if img.width().max(img.height()) > MAX_EDGE {
        img.resize(MAX_EDGE, MAX_EDGE, FilterType::Lanczos3)
    } else {
        img
    };
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
    fn picks_largest_embedded_jpeg_from_raw_container() {
        let mut raw = b"FAKE-RAW-HEADER".to_vec();
        raw.extend(jpeg_bytes(160, 120)); // thumbnail
        raw.extend(vec![0x42; 4096]); // sensor data
        raw.extend(jpeg_bytes(1600, 1000)); // preview
        raw.extend(vec![0x17; 2048]);
        let img = largest_embedded_jpeg(&raw).unwrap();
        assert_eq!((img.width(), img.height()), (1600, 1000));
    }

    #[test]
    fn rejects_raw_with_only_thumbnail() {
        let mut raw = vec![0u8; 100];
        raw.extend(jpeg_bytes(160, 120));
        assert!(matches!(
            largest_embedded_jpeg(&raw),
            Err(PreviewError::TooSmall(160))
        ));
    }

    #[test]
    fn rejects_raw_without_jpeg() {
        assert!(matches!(
            largest_embedded_jpeg(&[1, 2, 3, 0xFF, 0xD8]),
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
