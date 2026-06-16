//! Python bindings for breezy-hpss.
//!
//! Exposed to Python as `breezy._hpss_rs`. Functions and classes are added here
//! as the smart protocol is ported from `breezy/bzr/smart/` into the
//! `breezy-hpss` crate.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyTuple};

use breezy_hpss::body;
use breezy_hpss::protocol;
use breezy_hpss::protocol3;

fn protocol_err(py: Python<'_>, e: protocol::ProtocolError) -> PyErr {
    match e {
        protocol::ProtocolError::NotTerminated(line) => {
            PyValueError::new_err(format!("request {line:?} not terminated"))
        }
        protocol::ProtocolError::BadChunkedHeader(prefix)
        | protocol::ProtocolError::BadChunkLength(prefix) => smart_protocol_error(py, &prefix),
        // Mirrors int()/split() failures in the Python _deserialise_offsets.
        protocol::ProtocolError::BadOffset(line) => {
            PyValueError::new_err(format!("invalid readv offset line: {line:?}"))
        }
    }
}

/// Raise `dromedary.errors.SmartProtocolError`, falling back to `ValueError`
/// if it cannot be imported.
fn smart_protocol_error(py: Python<'_>, detail: &[u8]) -> PyErr {
    let msg = format!("smart protocol error: {detail:?}");
    match py
        .import("dromedary.errors")
        .and_then(|m| m.getattr("SmartProtocolError"))
    {
        Ok(cls) => match cls.call1((msg.clone(),)) {
            Ok(inst) => PyErr::from_value(inst),
            Err(_) => PyValueError::new_err(msg),
        },
        Err(_) => PyValueError::new_err(msg),
    }
}

/// Decode a smart-protocol tuple line into a tuple of byte strings.
///
/// Returns `None` for an empty or missing line.
#[pyfunction]
#[pyo3(name = "_decode_tuple")]
fn decode_tuple<'py>(
    py: Python<'py>,
    req_line: Option<&[u8]>,
) -> PyResult<Option<Bound<'py, PyTuple>>> {
    match protocol::decode_tuple(req_line) {
        Ok(None) => Ok(None),
        Ok(Some(fields)) => {
            let items: Vec<Bound<'py, PyBytes>> =
                fields.iter().map(|f| PyBytes::new(py, f)).collect();
            Ok(Some(PyTuple::new(py, items)?))
        }
        Err(e) => Err(protocol_err(py, e)),
    }
}

/// Encode a sequence of byte fields into a smart-protocol tuple line.
#[pyfunction]
#[pyo3(name = "_encode_tuple")]
fn encode_tuple<'py>(py: Python<'py>, args: Vec<Vec<u8>>) -> Bound<'py, PyBytes> {
    PyBytes::new(py, &protocol::encode_tuple(args))
}

/// Encode bulk data as a length-prefixed chunk (`_encode_bulk_data`).
#[pyfunction]
#[pyo3(name = "_encode_bulk_data")]
fn encode_bulk_data<'py>(py: Python<'py>, body: &[u8]) -> Bound<'py, PyBytes> {
    PyBytes::new(py, &protocol::encode_bulk_data(body))
}

/// Serialise readv `(start, length)` offsets (`_serialise_offsets`).
#[pyfunction]
#[pyo3(name = "_serialise_offsets")]
fn serialise_offsets<'py>(py: Python<'py>, offsets: Vec<(u64, u64)>) -> Bound<'py, PyBytes> {
    PyBytes::new(py, &protocol::serialise_offsets(&offsets))
}

/// Parse readv offsets serialised by `_serialise_offsets` (`_deserialise_offsets`).
#[pyfunction]
#[pyo3(name = "_deserialise_offsets")]
fn deserialise_offsets(py: Python<'_>, text: &[u8]) -> PyResult<Vec<(u64, u64)>> {
    protocol::deserialise_offsets(text).map_err(|e| protocol_err(py, e))
}

/// v3 framing: a length-prefixed bencode dict of byte-string header pairs.
#[pyfunction]
#[pyo3(name = "_v3_headers")]
fn v3_headers<'py>(py: Python<'py>, headers: Vec<(Vec<u8>, Vec<u8>)>) -> Bound<'py, PyBytes> {
    PyBytes::new(py, &protocol3::headers(&headers))
}

/// v3 framing: a `s` marker plus length-prefixed bencode list of byte args.
#[pyfunction]
#[pyo3(name = "_v3_structure")]
fn v3_structure<'py>(py: Python<'py>, args: Vec<Vec<u8>>) -> Bound<'py, PyBytes> {
    PyBytes::new(py, &protocol3::structure(&args))
}

/// v3 framing: a `b` marker plus length-prefixed raw body bytes.
#[pyfunction]
#[pyo3(name = "_v3_prefixed_body")]
fn v3_prefixed_body<'py>(py: Python<'py>, body: &[u8]) -> Bound<'py, PyBytes> {
    PyBytes::new(py, &protocol3::prefixed_body(body))
}

/// Decoder for length-prefixed bulk data (smart protocol v1 and v2).
#[pyclass(name = "LengthPrefixedBodyDecoder")]
struct PyLengthPrefixedBodyDecoder {
    inner: body::LengthPrefixedBodyDecoder,
}

#[pymethods]
impl PyLengthPrefixedBodyDecoder {
    #[new]
    fn new() -> Self {
        PyLengthPrefixedBodyDecoder {
            inner: body::LengthPrefixedBodyDecoder::new(),
        }
    }

    #[getter]
    fn finished_reading(&self) -> bool {
        self.inner.finished_reading()
    }

    #[getter]
    fn unused_data<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.inner.unused_data())
    }

    fn next_read_size(&self) -> usize {
        self.inner.next_read_size()
    }

    fn read_pending_data<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.inner.read_pending_data())
    }

    fn accept_bytes(&mut self, py: Python<'_>, new_buf: &[u8]) -> PyResult<()> {
        self.inner
            .accept_bytes(new_buf)
            .map_err(|e| protocol_err(py, e))
    }
}

/// Decoder for chunked transfer encoding (smart protocol v2+).
#[pyclass(name = "ChunkedBodyDecoder")]
struct PyChunkedBodyDecoder {
    inner: body::ChunkedBodyDecoder,
}

#[pymethods]
impl PyChunkedBodyDecoder {
    #[new]
    fn new() -> Self {
        PyChunkedBodyDecoder {
            inner: body::ChunkedBodyDecoder::new(),
        }
    }

    #[getter]
    fn finished_reading(&self) -> bool {
        self.inner.finished_reading()
    }

    #[getter]
    fn unused_data<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.inner.unused_data())
    }

    fn next_read_size(&self) -> usize {
        self.inner.next_read_size()
    }

    fn accept_bytes(&mut self, py: Python<'_>, new_buf: &[u8]) -> PyResult<()> {
        self.inner
            .accept_bytes(new_buf)
            .map_err(|e| protocol_err(py, e))
    }

    /// Return the next chunk: `bytes` for data, or a `FailedSmartServerResponse`
    /// for an error chunk, or `None` if no chunk is ready.
    fn read_next_chunk<'py>(&mut self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyAny>>> {
        match self.inner.read_next_chunk() {
            None => Ok(None),
            Some(body::Chunk::Data(data)) => Ok(Some(PyBytes::new(py, &data).into_any())),
            Some(body::Chunk::Error(args)) => {
                let arg_tuple = PyTuple::new(
                    py,
                    args.iter().map(|a| PyBytes::new(py, a)).collect::<Vec<_>>(),
                )?;
                let cls = py
                    .import("breezy.bzr.smart.request")?
                    .getattr("FailedSmartServerResponse")?;
                Ok(Some(cls.call1((arg_tuple,))?))
            }
        }
    }
}

#[pymodule]
fn _hpss_rs(_py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(decode_tuple, m)?)?;
    m.add_function(wrap_pyfunction!(encode_tuple, m)?)?;
    m.add_function(wrap_pyfunction!(encode_bulk_data, m)?)?;
    m.add_function(wrap_pyfunction!(serialise_offsets, m)?)?;
    m.add_function(wrap_pyfunction!(deserialise_offsets, m)?)?;
    m.add_function(wrap_pyfunction!(v3_headers, m)?)?;
    m.add_function(wrap_pyfunction!(v3_structure, m)?)?;
    m.add_function(wrap_pyfunction!(v3_prefixed_body, m)?)?;
    m.add_class::<PyLengthPrefixedBodyDecoder>()?;
    m.add_class::<PyChunkedBodyDecoder>()?;
    Ok(())
}
