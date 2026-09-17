//! Construction of the email messages breezy sends.
//!
//! This reproduces the subset of Python's `email` package that breezy relies
//! on, including its header ordering and encoding choices, so that generated
//! messages stay byte-for-byte identical.

pub mod address;
pub mod encoding;
pub mod message;

pub use address::{address_to_encoded_header, formataddr, parseaddr, Address, NonAsciiAddress};
pub use encoding::{detect_encoding, encode_payload, encode_str, rfc2047_encode, BodyEncoding};
pub use message::{Body, EmailMessage, MessageError};
