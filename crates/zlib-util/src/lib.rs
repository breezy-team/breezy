use flate2::write::DeflateEncoder;
use flate2::Compression;
use std::io::Write;

pub fn python_default_deflate_encoder<I: Write>(input: I) -> DeflateEncoder<I> {
    let compression = Compression::new(6);
    DeflateEncoder::new(input, compression)
}

pub mod estimator;
