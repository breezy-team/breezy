//! Assembling a complete RFC 2822 message.

use std::borrow::Cow;
use std::collections::BTreeMap;

use crate::email_message::address::{address_to_encoded_header, NonAsciiAddress};
use crate::email_message::encoding::{
    detect_encoding, encode_payload, encode_str, rfc2047_encode, BodyEncoding,
};

/// Why a message could not be built or rendered.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MessageError {
    /// A header value contained a line break, which would inject a header.
    EmbeddedHeader(String),
    /// An address was not ASCII, which RFCs do not permit.
    NonAsciiAddress,
}

impl std::fmt::Display for MessageError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            MessageError::EmbeddedHeader(value) => write!(
                f,
                "header value appears to contain an embedded header: {value:?}"
            ),
            MessageError::NonAsciiAddress => f.write_str("address must be ASCII"),
        }
    }
}

impl std::error::Error for MessageError {}

impl From<NonAsciiAddress> for MessageError {
    fn from(_: NonAsciiAddress) -> Self {
        MessageError::NonAsciiAddress
    }
}

/// Reject a header value that would inject a second header.
///
/// Python raises rather than emitting these, and so do we: writing them
/// through would let a crafted subject or filename forge headers.
fn check_header_value(value: &str) -> Result<(), MessageError> {
    if value.contains(['\r', '\n']) {
        return Err(MessageError::EmbeddedHeader(value.to_string()));
    }
    Ok(())
}

/// A body supplied as either text or raw bytes.
///
/// Text is always encodable, so it never ends up labelled 8-bit; bytes are
/// passed through and sniffed.
#[derive(Debug, Clone)]
pub enum Body {
    /// Text, which is always encodable as ASCII or UTF-8.
    Text(String),
    /// Raw bytes, whose encoding is sniffed.
    Bytes(Vec<u8>),
}

impl Body {
    /// Encode the body and report the charset it should be sent with.
    fn encode(&self) -> (Cow<'_, [u8]>, BodyEncoding) {
        match self {
            Body::Text(s) => {
                let (bytes, encoding) = encode_str(s);
                (Cow::Owned(bytes), encoding)
            }
            Body::Bytes(b) => (Cow::Borrowed(b.as_slice()), detect_encoding(b)),
        }
    }
}

/// An inline attachment.
#[derive(Debug, Clone)]
struct Part {
    body: Body,
    filename: Option<String>,
    mime_subtype: String,
}

/// The boundary Python's email package would generate is random; callers that
/// do not supply one get this fixed value instead.
const DEFAULT_BOUNDARY: &str = "===============0000000000==";

/// An email message under construction.
///
/// Holds headers and either a single body or a list of inline parts, and
/// renders them as a MIME message.
#[derive(Debug, Clone)]
pub struct EmailMessage {
    headers: BTreeMap<String, String>,
    body: Option<Body>,
    parts: Vec<Part>,
}

impl EmailMessage {
    /// Create a message with the given origin, destinations and subject.
    ///
    /// The subject is RFC2047-encoded if needed; each destination is encoded
    /// individually and joined with commas.
    pub fn new(
        from_address: &str,
        to_addresses: &[String],
        subject: &str,
        body: Option<Body>,
        user_agent: &str,
    ) -> Result<Self, MessageError> {
        let to = to_addresses
            .iter()
            .map(|a| address_to_encoded_header(a))
            .collect::<Result<Vec<_>, _>>()?
            .join(", ");

        check_header_value(subject)?;
        check_header_value(user_agent)?;

        let mut headers = BTreeMap::new();
        headers.insert("To".to_string(), to);
        headers.insert("From".to_string(), address_to_encoded_header(from_address)?);
        headers.insert("Subject".to_string(), rfc2047_encode(subject));
        headers.insert("User-Agent".to_string(), user_agent.to_string());

        Ok(EmailMessage {
            headers,
            body,
            parts: Vec::new(),
        })
    }

    /// Get a header, or `None` if it is not set.
    pub fn get(&self, header: &str) -> Option<&str> {
        self.headers.get(header).map(String::as_str)
    }

    /// Set a header, replacing any previous value.
    pub fn set(&mut self, header: &str, value: &str) -> Result<(), MessageError> {
        check_header_value(header)?;
        check_header_value(value)?;
        self.headers
            .insert(header.to_string(), rfc2047_encode(value));
        Ok(())
    }

    /// Attach a body to be displayed inline.
    ///
    /// The first call moves any body passed to `new` into the part list, so
    /// that it becomes the first attachment of the resulting multipart
    /// message.
    pub fn add_inline_attachment(
        &mut self,
        body: Body,
        filename: Option<&str>,
        mime_subtype: &str,
    ) -> Result<(), MessageError> {
        if let Some(filename) = filename {
            check_header_value(filename)?;
        }
        check_header_value(mime_subtype)?;
        if let Some(existing) = self.body.take() {
            self.parts.push(Part {
                body: existing,
                filename: None,
                mime_subtype: "plain".to_string(),
            });
        }
        self.parts.push(Part {
            body,
            filename: filename.map(str::to_string),
            mime_subtype: mime_subtype.to_string(),
        });
        Ok(())
    }

    /// Render the whole message, using `boundary` between MIME parts.
    ///
    /// A boundary is only needed when there are attachments; it is a parameter
    /// so that tests can produce stable output.
    pub fn as_bytes(&self, boundary: Option<&str>) -> Vec<u8> {
        if self.parts.is_empty() {
            self.render_simple()
        } else {
            self.render_multipart(boundary.unwrap_or(DEFAULT_BOUNDARY))
        }
    }

    /// Render a message with no attachments.
    fn render_simple(&self) -> Vec<u8> {
        let mut out = Vec::new();
        match &self.body {
            Some(body) => {
                let (payload, encoding) = body.encode();
                push_header(&mut out, "MIME-Version", "1.0");
                push_header(
                    &mut out,
                    "Content-Type",
                    &format!("text/plain; charset=\"{}\"", encoding.charset_name()),
                );
                push_header(
                    &mut out,
                    "Content-Transfer-Encoding",
                    encoding.transfer_encoding(),
                );
                self.push_headers(&mut out);
                out.push(b'\n');
                out.extend_from_slice(&encode_payload(&payload, encoding));
            }
            None => {
                self.push_headers(&mut out);
                out.push(b'\n');
            }
        }
        out
    }

    /// Render a multipart/mixed message.
    fn render_multipart(&self, boundary: &str) -> Vec<u8> {
        let mut out = Vec::new();
        push_header(
            &mut out,
            "Content-Type",
            &format!("multipart/mixed; boundary=\"{boundary}\""),
        );
        push_header(&mut out, "MIME-Version", "1.0");
        self.push_headers(&mut out);
        out.push(b'\n');

        for part in &self.parts {
            out.extend_from_slice(format!("--{boundary}\n").as_bytes());
            out.extend_from_slice(&render_part(part));
            // A boundary always starts on a fresh line, even when the payload
            // already ended with a newline.
            out.push(b'\n');
        }
        out.extend_from_slice(format!("--{boundary}--\n").as_bytes());
        out
    }

    /// Append the user-set headers, sorted by name.
    ///
    /// Values are stored already encoded, so that reading a header back yields
    /// the same text that goes on the wire.
    fn push_headers(&self, out: &mut Vec<u8>) {
        for (header, value) in &self.headers {
            push_header(out, header, value);
        }
    }
}

/// Append a single `Name: value` header line.
fn push_header(out: &mut Vec<u8>, name: &str, value: &str) {
    out.extend_from_slice(format!("{name}: {value}\n").as_bytes());
}

/// Render one inline part, headers and payload.
///
/// The header order differs between ASCII and non-ASCII parts. That is a quirk
/// of `MIMEText`, which sets Content-Type before MIME-Version only when it has
/// to pass an explicit charset object; it is reproduced here so output matches
/// byte for byte.
fn render_part(part: &Part) -> Vec<u8> {
    let (payload, encoding) = part.body.encode();
    let mut content_type = format!(
        "text/{}; charset=\"{}\"",
        part.mime_subtype,
        encoding.charset_name()
    );
    if let Some(filename) = &part.filename {
        content_type.push_str(&format!("; name=\"{filename}\""));
    }

    let mut out = Vec::new();
    if encoding == BodyEncoding::Ascii {
        push_header(&mut out, "MIME-Version", "1.0");
        push_header(&mut out, "Content-Type", &content_type);
    } else {
        push_header(&mut out, "Content-Type", &content_type);
        push_header(&mut out, "MIME-Version", "1.0");
    }
    push_header(
        &mut out,
        "Content-Transfer-Encoding",
        encoding.transfer_encoding(),
    );
    push_header(&mut out, "Content-Disposition", "inline");
    out.push(b'\n');
    out.extend_from_slice(&encode_payload(&payload, encoding));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    const UA: &str = "Bazaar (3.4.0)";
    const BOUNDARY: &str = "=====123456==";

    fn message(body: Option<Body>) -> EmailMessage {
        EmailMessage::new(
            "from@from.com",
            &["to@to.com".to_string()],
            "subject",
            body,
            UA,
        )
        .unwrap()
    }

    fn rendered(msg: &EmailMessage, boundary: Option<&str>) -> String {
        String::from_utf8(msg.as_bytes(boundary)).unwrap()
    }

    #[test]
    fn empty_message_is_headers_only() {
        assert_eq!(
            "From: from@from.com\n\
             Subject: subject\n\
             To: to@to.com\n\
             User-Agent: Bazaar (3.4.0)\n\n",
            rendered(&message(None), None)
        );
    }

    #[test]
    fn ascii_body_is_sent_verbatim() {
        assert_eq!(
            "MIME-Version: 1.0\n\
             Content-Type: text/plain; charset=\"us-ascii\"\n\
             Content-Transfer-Encoding: 7bit\n\
             From: from@from.com\n\
             Subject: subject\n\
             To: to@to.com\n\
             User-Agent: Bazaar (3.4.0)\n\n\
             body",
            rendered(&message(Some(Body::Bytes(b"body".to_vec()))), None)
        );
    }

    #[test]
    fn utf8_body_is_base64_encoded() {
        let msg = message(Some(Body::Text("b\u{f3}dy".to_string())));
        assert_eq!(
            "MIME-Version: 1.0\n\
             Content-Type: text/plain; charset=\"utf-8\"\n\
             Content-Transfer-Encoding: base64\n\
             From: from@from.com\n\
             Subject: subject\n\
             To: to@to.com\n\
             User-Agent: Bazaar (3.4.0)\n\n\
             YsOzZHk=\n",
            rendered(&msg, None)
        );
    }

    #[test]
    fn undecodable_body_is_labelled_eight_bit() {
        let msg = message(Some(Body::Bytes(b"b\xf4dy".to_vec())));
        assert_eq!(
            "MIME-Version: 1.0\n\
             Content-Type: text/plain; charset=\"8-bit\"\n\
             Content-Transfer-Encoding: base64\n\
             From: from@from.com\n\
             Subject: subject\n\
             To: to@to.com\n\
             User-Agent: Bazaar (3.4.0)\n\n\
             YvRkeQ==\n",
            rendered(&msg, None)
        );
    }

    #[test]
    fn attachment_turns_message_into_multipart() {
        let mut msg = message(None);
        msg.add_inline_attachment(Body::Text("body".to_string()), None, "plain")
            .unwrap();
        assert_eq!(
            format!(
                "Content-Type: multipart/mixed; boundary=\"{BOUNDARY}\"\n\
                 MIME-Version: 1.0\n\
                 From: from@from.com\n\
                 Subject: subject\n\
                 To: to@to.com\n\
                 User-Agent: Bazaar (3.4.0)\n\n\
                 --{BOUNDARY}\n\
                 MIME-Version: 1.0\n\
                 Content-Type: text/plain; charset=\"us-ascii\"\n\
                 Content-Transfer-Encoding: 7bit\n\
                 Content-Disposition: inline\n\n\
                 body\n\
                 --{BOUNDARY}--\n"
            ),
            rendered(&msg, Some(BOUNDARY))
        );
    }

    #[test]
    fn existing_body_becomes_the_first_part() {
        let mut msg = message(Some(Body::Text("body".to_string())));
        msg.add_inline_attachment(
            Body::Text("a\nb\nc\nd\ne\n".to_string()),
            Some("lines.txt"),
            "x-subtype",
        )
        .unwrap();
        let out = rendered(&msg, Some(BOUNDARY));
        assert!(out.contains("Content-Disposition: inline\n\nbody\n"));
        assert!(out.contains("text/x-subtype; charset=\"us-ascii\"; name=\"lines.txt\""));
        assert!(out.ends_with("a\nb\nc\nd\ne\n\n--=====123456==--\n"));
    }

    #[test]
    fn subjects_are_encoded_when_set() {
        let msg = EmailMessage::new(
            "from@from.com",
            &["to@to.com".to_string()],
            "P\u{e9}rez",
            None,
            UA,
        )
        .unwrap();
        assert_eq!(Some("=?utf-8?b?UMOpcmV6?="), msg.get("Subject"));
        assert!(rendered(&msg, None).contains("Subject: =?utf-8?b?UMOpcmV6?=\n"));
    }

    #[test]
    fn encoded_addresses_are_not_encoded_twice() {
        let msg = EmailMessage::new(
            "Pepe P\u{e9}rez <pperez@ejemplo.com>",
            &["to@to.com".to_string()],
            "subject",
            None,
            UA,
        )
        .unwrap();
        assert!(rendered(&msg, None)
            .contains("From: =?utf-8?q?Pepe_P=C3=A9rez?= <pperez@ejemplo.com>\n"));
    }

    #[test]
    fn multiple_destinations_are_comma_separated() {
        let msg = EmailMessage::new(
            "from@from.com",
            &[
                "to1@to.com".to_string(),
                "to2@to.com".to_string(),
                "to3@to.com".to_string(),
            ],
            "subject",
            None,
            UA,
        )
        .unwrap();
        assert_eq!(Some("to1@to.com, to2@to.com, to3@to.com"), msg.get("To"));
    }

    #[test]
    fn headers_can_be_read_and_replaced() {
        let mut msg = message(None);
        assert_eq!(Some("from@from.com"), msg.get("From"));
        assert_eq!(None, msg.get("Does-Not-Exist"));
        msg.set("To", "to2@to.com").unwrap();
        msg.set("Cc", "cc@cc.com").unwrap();
        assert_eq!(Some("to2@to.com"), msg.get("To"));
        assert_eq!(Some("cc@cc.com"), msg.get("Cc"));
    }

    #[test]
    fn rejects_header_values_containing_line_breaks() {
        assert_eq!(
            Err(MessageError::EmbeddedHeader(
                "evil\nBcc: a@evil.com".to_string()
            )),
            EmailMessage::new(
                "from@from.com",
                &["to@to.com".to_string()],
                "evil\nBcc: a@evil.com",
                None,
                UA,
            )
            .map(|_| ())
        );

        let mut msg = message(None);
        assert!(msg.set("Cc", "a@b.com\nBcc: c@d.com").is_err());
        assert!(msg
            .add_inline_attachment(Body::Text("x".to_string()), Some("a\nb.txt"), "plain")
            .is_err());
        assert!(msg
            .add_inline_attachment(Body::Text("x".to_string()), None, "plain\nX-Evil: 1")
            .is_err());
    }

    #[test]
    fn rejects_non_ascii_addresses() {
        assert_eq!(
            Err(MessageError::NonAsciiAddress),
            EmailMessage::new(
                "Name <p\u{e9}rez@x.com>",
                &["to@to.com".to_string()],
                "subject",
                None,
                UA,
            )
            .map(|_| ())
        );
    }

    #[test]
    fn normalizes_line_endings_in_plain_bodies() {
        let msg = message(Some(Body::Bytes(b"a\r\nb\rc".to_vec())));
        assert!(rendered(&msg, None).ends_with("\n\na\nb\nc"));
    }
}
