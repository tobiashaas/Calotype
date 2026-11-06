//! Build Bridge previews for real files, to check extraction on a RAW corpus:
//!
//!     cargo run -p lrff-bridge-core --example preview -- <out-dir> <file>...

use std::path::{Path, PathBuf};
use std::time::Instant;

fn main() {
    let mut args = std::env::args_os().skip(1);
    let out_dir = PathBuf::from(args.next().expect("usage: preview <out-dir> <file>..."));
    std::fs::create_dir_all(&out_dir).expect("create out dir");
    let mut failed = 0;
    for file in args.map(PathBuf::from) {
        let started = Instant::now();
        match lrff_bridge_core::preview::build_preview(&file) {
            Ok(jpeg) => {
                let img = image::load_from_memory(&jpeg).expect("own output decodes");
                let out = out_dir.join(stem(&file)).with_extension("jpg");
                std::fs::write(&out, &jpeg).expect("write preview");
                println!(
                    "ok   {}  {}x{}  {} KB  {} ms",
                    file.display(),
                    img.width(),
                    img.height(),
                    jpeg.len() / 1024,
                    started.elapsed().as_millis()
                );
            }
            Err(e) => {
                failed += 1;
                println!("FAIL {}  {e}", file.display());
            }
        }
    }
    std::process::exit(if failed > 0 { 1 } else { 0 });
}

fn stem(path: &Path) -> String {
    path.file_stem()
        .unwrap_or_default()
        .to_string_lossy()
        .into_owned()
}
