use crate::rio::valid_tag;
use crate::rio::{Stanza,StanzaValue};

#[test]
fn test_valid_tag() {
    assert!(valid_tag("name"));
    assert!(!valid_tag("!name"));
}

#[test]
fn test_stanza() {
    let mut s = Stanza::new();
    s.add("number".to_string(), StanzaValue::String("42".to_string()));
    s.add("name".to_string(), StanzaValue::String("fred".to_string()));

    assert!(s.contains("number"));
    assert!(!s.contains("color"));
    assert!(!s.contains("42"));

    // Verify that the s.get() function works
    assert_eq!(s.get("number"), Some(&StanzaValue::String("42".to_string())));
    assert_eq!(s.get("name"), Some(&StanzaValue::String("fred".to_string())));
    assert_eq!(s.get("color"), None);

    // Verify that iter_pairs() works
    assert_eq!(s.iter_pairs().count(), 2);
}

#[test]
fn test_eq() {
    let mut s = Stanza::new();
    s.add("number".to_string(), StanzaValue::String("42".to_string()));
    s.add("name".to_string(), StanzaValue::String("fred".to_string()));

    let mut t = Stanza::new();
    t.add("number".to_string(), StanzaValue::String("42".to_string()));
    t.add("name".to_string(), StanzaValue::String("fred".to_string()));

    assert_eq!(s, s);
    assert_eq!(s, t);
    t.add("color".to_string(), StanzaValue::String("red".to_string()));

    assert_ne!(s, t);
}

#[test]
fn test_empty_value() {
    let s = Stanza::from_pairs(vec![("empty".to_string(), StanzaValue::String("".to_string()))]);
    assert_eq!(s.to_string(), "empty: \n");
}

#[test]
fn test_to_lines() {
    let s = Stanza::from_pairs(vec![
        ("number".to_string(), StanzaValue::String("42".to_string())),
        ("name".to_string(), StanzaValue::String("fred".to_string())),
    ]);
    assert_eq!(
        s.to_lines(),
        vec!["number: 42\n".to_string(), "name: fred\n".to_string()]
    );
}
