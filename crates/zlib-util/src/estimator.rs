use crate::python_default_deflate_encoder;
use flate2::write::DeflateEncoder;
use std::io::Write;

pub struct ZLibEstimator {
    target_size: usize,
    compressor: DeflateEncoder<Vec<u8>>,
    uncompressed_size_added: usize,
    compressed_size_added: usize,
    unflushed_size_added: usize,
    estimated_compression: f32,
}

impl ZLibEstimator {
    pub fn new(target_size: usize) -> Self {
        Self {
            target_size,
            compressor: python_default_deflate_encoder(Vec::new()),
            uncompressed_size_added: 0,
            compressed_size_added: 0,
            unflushed_size_added: 0,
            estimated_compression: 2.0,
        }
    }

    pub fn compressed_size_added(&self) -> usize {
        self.compressed_size_added
    }

    pub fn uncompressed_size_added(&self) -> usize {
        self.uncompressed_size_added
    }

    pub fn add_content(&mut self, content: &[u8]) -> std::io::Result<()> {
        self.uncompressed_size_added += content.len();
        self.unflushed_size_added += content.len();
        self.compressor.write_all(content)?;
        let compressed_content = self.compressor.get_ref().to_vec();
        let z_size = compressed_content.len();
        if z_size > 0 {
            self.record_z_len(z_size);
        }
        self.compressor.get_mut().clear();
        Ok(())
    }

    fn record_z_len(&mut self, count: usize) {
        // We got some compressed bytes, update the counters
        self.compressed_size_added += count;
        self.unflushed_size_added = 0;
        // So far we've read X uncompressed bytes, and written Y compressed
        // bytes. We should have a decent estimate of the final compression.
        self.estimated_compression =
            (self.uncompressed_size_added as f32) / (self.compressed_size_added as f32);
    }

    pub fn full(&mut self) -> std::io::Result<bool> {
        // Have we reached the target size?
        if self.unflushed_size_added > 0 {
            let remaining_size = self.target_size - self.compressed_size_added;
            // Estimate how much compressed content the unflushed data will
            // consume
            let est_z_size = (self.unflushed_size_added as f32) / self.estimated_compression;
            if est_z_size >= remaining_size as f32 {
                // We estimate we are close to remaining
                self.compressor.flush()?;
                let compressed_content = self.compressor.get_ref().to_vec();
                let z_size = compressed_content.len();
                self.record_z_len(z_size);
                self.compressor.get_mut().clear();
            }
        }
        Ok(self.compressed_size_added >= self.target_size)
    }
}
