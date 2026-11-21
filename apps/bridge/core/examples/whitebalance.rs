//! Print the camera-measured colour temperature of RAW files, to compare with ExifTool:
//!
//!     cargo run --release -p calotype-bridge-core --example whitebalance -- <raw files>
//!     exiftool -n -ColorTempMeasured <raw files>

use std::path::Path;

fn main() {
    for arg in std::env::args().skip(1) {
        let name = Path::new(&arg)
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default();
        match calotype_bridge_core::whitebalance::measured_kelvin(Path::new(&arg)) {
            Some(kelvin) => println!("{name}\t{kelvin}"),
            None => println!("{name}\t-"),
        }
    }
}
