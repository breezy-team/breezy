pub mod hg;
pub mod roundtrip;

pub fn bzr_url_to_git_url(
    location: &str,
) -> Result<(String, Option<String>, Option<String>), dromedary::urlutils::Error> {
    let (target_url, target_params) = dromedary::urlutils::split_segment_parameters(location)?;
    let branch = target_params.get("branch").map(|s| s.to_string());
    let ref_ = target_params.get("ref").map(|s| s.to_string());
    Ok((target_url.to_string(), branch, ref_))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bzr_url_to_git_url() {
        assert_eq!(
            bzr_url_to_git_url("git+ssh://foo/bar/path,branch=blah,ref=refs%2Ftags%2Fblah")
                .unwrap(),
            (
                "git+ssh://foo/bar/path".to_string(),
                Some("blah".to_string()),
                Some("refs%2Ftags%2Fblah".to_string())
            )
        );
        assert_eq!(
            bzr_url_to_git_url("git+ssh://foo/bar/path,revno=3").unwrap(),
            ("git+ssh://foo/bar/path".to_string(), None, None)
        );
    }
}

pub fn get_cache_dir() -> std::io::Result<std::path::PathBuf> {
    let path = breezy::bedding::cache_dir()?.join("git");

    if !path.is_dir() {
        std::fs::create_dir_all(&path)?;
    }
    Ok(path)
}
