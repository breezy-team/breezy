use lazy_static::lazy_static;
use regex::Regex;

lazy_static! {
    static ref SLASHES: Regex = Regex::new(r"[\\/]+").unwrap();
}

/// Converts backslashes in path patterns to forward slashes.
/// Doesn't normalize regular expressions - they may contain escapes.
pub fn normalize_pattern(pattern: &str) -> String {
    let mut pattern = pattern.to_string();
    if !(pattern.starts_with("RE:") || pattern.starts_with("!RE:")) {
        pattern = SLASHES.replace_all(pattern.as_str(), "/").to_string();
    }
    if pattern.len() > 1 {
        pattern = pattern.trim_end_matches('/').to_string();
    }
    return pattern;
}
