use std::path::{Path, PathBuf};

pub fn get_brz_log_filename() -> Result<PathBuf, std::io::Error> {
    let brz_log = std::env::var("BRZ_LOG").ok();
    if let Some(brz_log) = brz_log {
        Ok(PathBuf::from(brz_log))
    } else {
        let cache_dir = crate::bedding::cache_dir()?;
        Ok(cache_dir.join("brz.log"))
    }
}
