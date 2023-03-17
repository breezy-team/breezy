use crate::rio::valid_tag;

#[test]
fn test_valid_tag() {
    assert!(valid_tag("name"));
    assert!(!valid_tag("!name"));
}
