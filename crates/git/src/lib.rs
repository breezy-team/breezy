pub fn bzr_url_to_git_url(
    location: &str,
) -> Result<(String, Option<String>, Option<String>), breezy_urlutils::Error> {
    let (target_url, target_params) = breezy_urlutils::split_segment_parameters(location)?;
    let branch = target_params.get("branch").map(|s| s.to_string());
    let ref_ = target_params.get("revno").map(|s| s.to_string());
    Ok((target_url.to_string(), branch, ref_))
}

pub fn get_cache_dir() -> std::io::Result<std::path::PathBuf> {
    let path = breezy::bedding::cache_dir()?.join("git");

    if !path.is_dir() {
        std::fs::create_dir_all(&path)?;
    }
    Ok(path)
}
