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

pub fn get_cache_dir() -> std::io::Result<std::path::PathBuf> {
    let path = breezy::bedding::cache_dir()?.join("git");

    if !path.is_dir() {
        std::fs::create_dir_all(&path)?;
    }
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parsed(location: &str) -> (String, Option<String>, Option<String>) {
        bzr_url_to_git_url(location).unwrap()
    }

    #[test]
    fn plain_url() {
        assert_eq!(
            parsed("git+ssh://foo/bar/path"),
            ("git+ssh://foo/bar/path".to_string(), None, None)
        );
    }

    #[test]
    fn branch_parameter() {
        assert_eq!(
            parsed("git+ssh://foo/bar/path,branch=foo%2Fblah"),
            (
                "git+ssh://foo/bar/path".to_string(),
                Some("foo%2Fblah".to_string()),
                None
            )
        );
    }

    #[test]
    fn ref_parameter() {
        assert_eq!(
            parsed("git+ssh://foo/bar/path,ref=refs%2Ftags%2Fblah"),
            (
                "git+ssh://foo/bar/path".to_string(),
                None,
                Some("refs%2Ftags%2Fblah".to_string())
            )
        );
    }

    #[test]
    fn branch_and_ref() {
        assert_eq!(
            parsed("git+ssh://foo/bar/path,branch=blah,ref=refs%2Ftags%2Fblah"),
            (
                "git+ssh://foo/bar/path".to_string(),
                Some("blah".to_string()),
                Some("refs%2Ftags%2Fblah".to_string())
            )
        );
    }

    #[test]
    fn revno_is_not_ref() {
        assert_eq!(
            parsed("git+ssh://foo/bar/path,revno=3"),
            ("git+ssh://foo/bar/path".to_string(), None, None)
        );
    }
}
