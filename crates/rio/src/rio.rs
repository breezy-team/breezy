use regex::Regex;

/// Verify whether a tag is validly formatted
pub fn valid_tag(tag: &str) -> bool {
    lazy_static! {
        static ref RE: Regex = Regex::new(r"^[-a-zA-Z0-9_]+$").unwrap();
    }
    RE.is_match(tag)
}
