//! Splitting and reassembling `Real Name <addr@example.com>` pairs.
//!
//! This tracks `email.utils.parseaddr`/`formataddr` rather than the RFCs,
//! because breezy re-parses its own rendered `To` header to pick SMTP envelope
//! recipients: parsing an address differently to CPython would change who
//! receives the mail, not just how a header looks.
//!
//! It is a deliberate approximation of CPython's `_parseaddr` state machine.
//! Realistic addresses -- quoted names, comments, non-ASCII display names --
//! match exactly; input that is mostly bare specials can still differ, and the
//! conservative answer there is an empty address, which reads as "no
//! destination" rather than as some other recipient. Third-party parsers were
//! evaluated and rejected: they are better parsers, but they disagree with
//! CPython on the `addr (Real Name)` and comment forms that breezy emits.

use crate::email_message::encoding::rfc2047_encode;

/// Characters that force the display name to be quoted, per RFC 2822.
///
/// Same set as `email.utils.specialsre`.
const SPECIALS: &[char] = &[
    '[', ']', '\\', '(', ')', '<', '>', '@', ',', ':', ';', '"', '.',
];

/// A display name and email address, as produced by `parseaddr`.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Address {
    /// The display name, empty when the address had none.
    pub name: String,
    /// The bare email address.
    pub addr: String,
}
/// Parse a phrase into its tokens, dropping quoting and comment parentheses.
///
/// RFC 2822 lets a phrase mix bare words, quoted strings and nested comments,
/// so `pre"mid"post` is three tokens. Python joins them with a single space.
/// Comment parentheses are dropped, except that `keep_outer_parens` retains
/// the outermost pair, which Python keeps when a comment precedes an
/// angle-addr. Returns None if a quote or comment is left open, which Python
/// treats as a parse failure rather than something to guess at.
fn parse_phrase(value: &str, keep_outer_parens: bool) -> Result<String, PhraseError> {
    let mut tokens: Vec<String> = Vec::new();
    let mut current = String::new();
    let mut in_quotes = false;
    let mut depth = 0usize;
    let mut chars = value.chars();

    while let Some(c) = chars.next() {
        // Specials are only legal inside a quoted string or a comment.
        if !in_quotes && depth == 0 && SPECIALS_BARE.contains(&c) {
            return Err(PhraseError::BareSpecial);
        }
        match c {
            '\\' if in_quotes || depth > 0 => {
                if let Some(next) = chars.next() {
                    current.push(next);
                }
            }
            '"' if depth == 0 => {
                if !current.is_empty() {
                    tokens.push(std::mem::take(&mut current));
                }
                in_quotes = !in_quotes;
            }
            '(' if !in_quotes => {
                if !current.is_empty() {
                    tokens.push(std::mem::take(&mut current));
                }
                depth += 1;
                if keep_outer_parens && depth == 1 {
                    current.push('(');
                }
            }
            ')' if !in_quotes && depth > 0 => {
                if keep_outer_parens && depth == 1 {
                    current.push(')');
                }
                if !current.is_empty() {
                    tokens.push(std::mem::take(&mut current));
                }
                depth -= 1;
            }
            c if c.is_whitespace() && !in_quotes => {
                if !current.is_empty() {
                    tokens.push(std::mem::take(&mut current));
                }
            }
            c => current.push(c),
        }
    }
    if in_quotes || depth > 0 {
        return Err(PhraseError::Unterminated);
    }
    if !current.is_empty() {
        tokens.push(current);
    }
    Ok(tokens.join(" "))
}

/// Why a display phrase could not be parsed.
///
/// Python distinguishes these: a bare special makes the whole address
/// unparseable, while an unterminated quote makes it fall back to the leading
/// token.
enum PhraseError {
    BareSpecial,
    Unterminated,
}

/// Specials that may not appear bare in a display name.
///
/// They have to be quoted or inside a comment, so finding one loose means the
/// input is not a well-formed address and Python's parser gives up on it.
const SPECIALS_BARE: &[char] = &[',', ':', ';', '<', '>', '@', '[', ']'];

/// True if this text may appear outside quotes in an address.
fn is_well_formed(value: &str) -> bool {
    !value.contains(SPECIALS_BARE)
}

/// Split an address into its display name and email address.
///
/// Handles the forms breezy produces and receives: a bare address, an
/// `angle-addr` with an optional (possibly quoted) display name, and the
/// legacy `addr (Real Name)` comment form. Input that is not one of these
/// yields an empty result, matching `email.utils.parseaddr`, so a malformed
/// address is never silently turned into a deliverable one.
pub fn parseaddr(value: &str) -> Address {
    parse_address(value).unwrap_or_default()
}

/// The fallible core of [`parseaddr`]; None means the input is malformed.
fn parse_address(value: &str) -> Option<Address> {
    let value = value.trim();
    if value.is_empty() {
        return Some(Address::default());
    }

    if let Some(open) = value.find('<') {
        let close = value[open..].find('>')? + open;
        // Trailing text means this is not a single address.
        if !value[close + 1..].trim().is_empty() {
            return None;
        }
        let addr = value[open + 1..close].trim().to_string();
        if !is_well_formed(&addr.replace('@', "")) {
            return None;
        }
        // A comment here keeps its outer parentheses, which Python treats as
        // literal text of the display phrase. An unterminated quote means the
        // text is not a display name at all, so fall back to the bare token.
        let name = match parse_phrase(&value[..open], true) {
            Ok(name) => name,
            Err(PhraseError::Unterminated) => return bare_token(value),
            Err(PhraseError::BareSpecial) => return None,
        };
        return Some(Address { name, addr });
    }

    if let Some(open) = value.find('(') {
        let name = parse_phrase(&value[open..], false).ok()?;
        let addr = value[..open].trim().to_string();
        if !is_well_formed(&addr.replace('@', "")) {
            return None;
        }
        return Some(Address { name, addr });
    }

    bare_token(value)
}

/// Fall back to the leading whitespace-delimited token as the address.
fn bare_token(value: &str) -> Option<Address> {
    let addr = value
        .split_whitespace()
        .next()
        .unwrap_or("")
        .split('"')
        .next()
        .unwrap_or("")
        .to_string();
    if !is_well_formed(&addr.replace('@', "")) {
        return None;
    }
    Some(Address {
        name: String::new(),
        addr,
    })
}

/// An address that cannot be represented in a header.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NonAsciiAddress;

impl std::fmt::Display for NonAsciiAddress {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("address must be ASCII")
    }
}

impl std::error::Error for NonAsciiAddress {}

/// Render a name and address as a header value.
///
/// A non-ASCII display name is RFC2047-encoded; an ASCII one is quoted and
/// backslash-escaped only when it contains specials. An empty name yields the
/// bare address. Mirrors `email.utils.formataddr`, including its refusal to
/// encode the address itself, which RFCs do not permit.
pub fn formataddr(address: &Address) -> Result<String, NonAsciiAddress> {
    if !address.addr.is_ascii() {
        return Err(NonAsciiAddress);
    }
    if address.name.is_empty() {
        return Ok(address.addr.clone());
    }
    if !address.name.is_ascii() {
        return Ok(format!(
            "{} <{}>",
            rfc2047_encode(&address.name),
            address.addr
        ));
    }
    if address.name.contains(SPECIALS) {
        let escaped = address.name.replace('\\', "\\\\").replace('"', "\\\"");
        Ok(format!("\"{}\" <{}>", escaped, address.addr))
    } else {
        Ok(format!("{} <{}>", address.name, address.addr))
    }
}

/// RFC2047-encode an address if its display name requires it.
///
/// The address itself is never encoded, since RFCs do not permit it; only the
/// display name is.
pub fn address_to_encoded_header(address: &str) -> Result<String, NonAsciiAddress> {
    formataddr(&parseaddr(address))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parsed(name: &str, addr: &str) -> Address {
        Address {
            name: name.to_string(),
            addr: addr.to_string(),
        }
    }

    #[test]
    fn parses_bare_address() {
        assert_eq!(
            parsed("", "jrandom@example.com"),
            parseaddr("jrandom@example.com")
        );
    }

    #[test]
    fn parses_angle_addr() {
        assert_eq!(
            parsed("J Random Developer", "jrandom@example.com"),
            parseaddr("J Random Developer <jrandom@example.com>")
        );
        assert_eq!(parsed("", "a@b.com"), parseaddr("<a@b.com>"));
        assert_eq!(
            parsed("spaced", "a@b.com"),
            parseaddr("  spaced  <a@b.com>  ")
        );
    }

    #[test]
    fn parses_quoted_display_name() {
        assert_eq!(
            parsed("J. Random Developer", "jrandom@example.com"),
            parseaddr("\"J. Random Developer\" <jrandom@example.com>")
        );
        assert_eq!(
            parsed("quoted \" escape", "a@b.com"),
            parseaddr("\"quoted \\\" escape\" <a@b.com>")
        );
    }

    #[test]
    fn joins_display_name_tokens() {
        assert_eq!(
            parsed("weird name", "a@b.com"),
            parseaddr("weird \"name\" <a@b.com>")
        );
        assert_eq!(
            parsed("pre mid post", "x@y.com"),
            parseaddr("pre\"mid\"post <x@y.com>")
        );
    }

    #[test]
    fn parses_comment_form() {
        assert_eq!(
            parsed("Real Name", "a@b.com"),
            parseaddr("a@b.com (Real Name)")
        );
    }

    #[test]
    fn parses_degenerate_input() {
        assert_eq!(parsed("", ""), parseaddr(""));
        assert_eq!(parsed("", "not"), parseaddr("not an address"));
    }

    #[test]
    fn rejects_malformed_addresses() {
        // An unterminated quote or comment, trailing text after the
        // angle-addr, or a bare special all mean this is not one address.
        // Python yields an empty result for these, and so must we: guessing
        // could turn a malformed address into a deliverable one.
        for value in [
            "a <b> <c@d.com>",
            "foo <bar@baz.com> extra",
            "name with, comma <x@y.com>",
            "a@b.com, c@d.com",
            "a<b@c.com>d",
            "a@b.com (unterminated",
        ] {
            assert_eq!(parsed("", ""), parseaddr(value), "for {value:?}");
        }
        assert_eq!(parsed("", "a"), parseaddr("a\"b <x@y.com>"));
    }

    #[test]
    fn strips_nested_comment_parentheses() {
        assert_eq!(
            parsed("a nested b", "x@y.com"),
            parseaddr("x@y.com (a (nested) b)")
        );
        assert_eq!(parsed("ab", "a@b.com"), parseaddr("a@b.com (a\\b)"));
    }

    #[test]
    fn rejects_non_ascii_addresses() {
        assert_eq!(
            Err(NonAsciiAddress),
            address_to_encoded_header("Name <p\u{e9}rez@x.com>")
        );
    }

    #[test]
    fn round_trips_plain_addresses() {
        for address in [
            "jrandom@example.com",
            "J Random Developer <jrandom@example.com>",
            "\"J. Random Developer\" <jrandom@example.com>",
        ] {
            assert_eq!(Ok(address.to_string()), address_to_encoded_header(address));
        }
    }

    #[test]
    fn encodes_only_the_display_name() {
        assert_eq!(
            Ok("=?utf-8?q?Pepe_P=C3=A9rez?= <pperez@ejemplo.com>".to_string()),
            address_to_encoded_header("Pepe P\u{e9}rez <pperez@ejemplo.com>")
        );
    }

    #[test]
    fn quotes_names_containing_specials() {
        assert_eq!(
            Ok("\"a\\\"b(c)d,e:f;g<h>i@j[k]l\\\\m\" <x@y.com>".to_string()),
            formataddr(&parsed("a\"b(c)d,e:f;g<h>i@j[k]l\\m", "x@y.com"))
        );
    }
}
