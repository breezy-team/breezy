//! Python bindings for `breezy::email_message`, exposed as
//! `breezy._cmd_rs.email_message`.
//!
//! Backs `breezy.email_message`, which keeps the thin `EmailMessage` class and
//! its `send()` helper in Python while the encoding and serialization live
//! here.

use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString, PyTuple};

use breezy::email_message::{
    address_to_encoded_header, detect_encoding, encode_str, Body, EmailMessage, MessageError,
};

// Raised in place of BzrBadParameterNotUnicode, which the Python wrapper
// translates, so that bytes addresses keep their historical error.
pyo3::create_exception!(
    email_message,
    BadParameterNotUnicode,
    pyo3::exceptions::PyException,
    "An address was passed as bytes rather than str."
);

// Python's email package raises HeaderParseError for an embedded header and
// UnicodeEncodeError for a non-ASCII address; keep those distinguishable.
pyo3::create_exception!(
    email_message,
    HeaderParseError,
    pyo3::exceptions::PyValueError,
    "A header value could not be represented."
);

/// Map a message error onto the exception Python would have raised.
fn message_error(err: MessageError) -> PyErr {
    match err {
        MessageError::EmbeddedHeader(_) => HeaderParseError::new_err(err.to_string()),
        MessageError::NonAsciiAddress => PyValueError::new_err(err.to_string()),
    }
}

/// Convert a body argument, which may be `str` or `bytes`.
fn extract_body(obj: &Bound<'_, PyAny>) -> PyResult<Body> {
    if let Ok(s) = obj.cast::<PyString>() {
        Ok(Body::Text(s.extract()?))
    } else if let Ok(b) = obj.cast::<PyBytes>() {
        Ok(Body::Bytes(b.as_bytes().to_vec()))
    } else {
        Err(PyTypeError::new_err("body must be str or bytes"))
    }
}

/// RFC2047-encode an address if necessary.
///
/// Rejects bytes so that callers get the same error as before, rather than
/// silently mis-encoding a non-UTF-8 address.
#[pyfunction]
#[pyo3(name = "address_to_encoded_header")]
fn py_address_to_encoded_header(address: &Bound<'_, PyAny>) -> PyResult<String> {
    address_to_encoded_header(&extract_str(address)?)
        .map_err(|e| PyValueError::new_err(e.to_string()))
}

/// Return a body together with the encoding it should be sent with.
///
/// The pair is `(bytes, encoding)`, where encoding is one of `ascii`, `utf-8`
/// or `8-bit`, in that preferred order.
#[pyfunction]
#[pyo3(name = "string_with_encoding")]
fn py_string_with_encoding<'py>(
    py: Python<'py>,
    string: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyTuple>> {
    let (bytes, encoding) = match extract_body(string)? {
        Body::Text(s) => encode_str(&s),
        Body::Bytes(b) => {
            let encoding = detect_encoding(&b);
            (b, encoding)
        }
    };
    PyTuple::new(
        py,
        [
            PyBytes::new(py, &bytes).into_any(),
            PyString::new(py, encoding.name()).into_any(),
        ],
    )
}

/// An email message being built up for sending.
#[pyclass(name = "EmailMessage", module = "breezy._cmd_rs.email_message")]
struct PyEmailMessage {
    inner: EmailMessage,
}

#[pymethods]
impl PyEmailMessage {
    /// Create a message.
    ///
    /// `to_address` may be a single address or a list of them. Addresses and
    /// the subject must be str; the body may be str or bytes.
    #[new]
    #[pyo3(signature = (from_address, to_address, subject, body=None, user_agent=""))]
    fn new(
        from_address: &Bound<'_, PyAny>,
        to_address: &Bound<'_, PyAny>,
        subject: &Bound<'_, PyAny>,
        body: Option<&Bound<'_, PyAny>>,
        user_agent: &str,
    ) -> PyResult<Self> {
        let from_address = extract_str(from_address)?;
        let subject = extract_text(subject)?;

        let to_addresses =
            if to_address.is_instance_of::<PyString>() || to_address.is_instance_of::<PyBytes>() {
                vec![extract_str(to_address)?]
            } else {
                to_address
                    .try_iter()?
                    .map(|item| extract_str(&item?))
                    .collect::<PyResult<Vec<_>>>()?
            };

        let body = body
            .filter(|b| !b.is_none())
            .map(extract_body)
            .transpose()?;

        let inner = EmailMessage::new(&from_address, &to_addresses, &subject, body, user_agent)
            .map_err(message_error)?;
        Ok(PyEmailMessage { inner })
    }

    /// Add a text attachment to be displayed inline.
    #[pyo3(signature = (body, filename=None, mime_subtype="plain"))]
    fn add_inline_attachment(
        &mut self,
        body: &Bound<'_, PyAny>,
        filename: Option<&str>,
        mime_subtype: &str,
    ) -> PyResult<()> {
        self.inner
            .add_inline_attachment(extract_body(body)?, filename, mime_subtype)
            .map_err(message_error)
    }

    /// Return the entire formatted message as a string.
    #[pyo3(signature = (boundary=None))]
    fn as_string(&self, boundary: Option<&str>) -> PyResult<String> {
        let bytes = self.inner.as_bytes(boundary);
        // Bodies labelled 8-bit are not valid UTF-8, so fall back to latin-1,
        // which is what Python's email package effectively produces here.
        Ok(match String::from_utf8(bytes) {
            Ok(s) => s,
            Err(e) => e.as_bytes().iter().map(|&b| b as char).collect(),
        })
    }

    fn __str__(&self) -> PyResult<String> {
        self.as_string(None)
    }

    /// Get a header, returning `failobj` when it is not set.
    #[pyo3(signature = (header, failobj=None))]
    fn get(&self, py: Python<'_>, header: &str, failobj: Option<Py<PyAny>>) -> Py<PyAny> {
        match self.inner.get(header) {
            Some(value) => PyString::new(py, value).into_any().unbind(),
            None => failobj.unwrap_or_else(|| py.None()),
        }
    }

    /// Get a header, returning None when it is not set.
    ///
    /// Deliberately does not raise KeyError, mimicking `email.Message`.
    fn __getitem__(&self, py: Python<'_>, header: &str) -> Py<PyAny> {
        self.get(py, header, None)
    }

    /// Set a header.
    fn __setitem__(&mut self, header: &str, value: &str) -> PyResult<()> {
        self.inner.set(header, value).map_err(message_error)
    }
}

/// Extract a str, decoding bytes as UTF-8.
///
/// The subject has always accepted UTF-8 bytes, via `osutils.safe_unicode`.
/// Bytes that are not valid UTF-8 are rejected rather than guessed at.
fn extract_text(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    if let Ok(b) = obj.cast::<PyBytes>() {
        return match String::from_utf8(b.as_bytes().to_vec()) {
            Ok(s) => Ok(s),
            Err(_) => Err(BadParameterNotUnicode::new_err(obj.repr()?.to_string())),
        };
    }
    extract_str(obj)
}

/// Extract a str, rejecting bytes.
///
/// Addresses must already be text; RFCs do not permit encoding the address
/// itself, so accepting bytes here would mean guessing at their encoding.
fn extract_str(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    match obj.cast::<PyString>() {
        Ok(s) => s.extract(),
        Err(_) => Err(BadParameterNotUnicode::new_err(obj.repr()?.to_string())),
    }
}

/// Register the `email_message` submodule.
pub(crate) fn email_message(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyEmailMessage>()?;
    m.add_function(wrap_pyfunction!(py_address_to_encoded_header, m)?)?;
    m.add_function(wrap_pyfunction!(py_string_with_encoding, m)?)?;
    m.add(
        "BadParameterNotUnicode",
        m.py().get_type::<BadParameterNotUnicode>(),
    )?;
    m.add("HeaderParseError", m.py().get_type::<HeaderParseError>())?;
    Ok(())
}
