use bazaar::groupcompress::compressor::GroupCompressor;
use bazaar::versionedfile::Key;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3::wrap_pyfunction;
use std::convert::TryInto;

#[pyfunction]
fn encode_base128_int(py: Python, value: u128) -> PyResult<&PyBytes> {
    let ret = bazaar::groupcompress::delta::encode_base128_int(value);
    Ok(PyBytes::new(py, &ret))
}

#[pyfunction]
fn decode_base128_int(value: Vec<u8>) -> PyResult<(u128, usize)> {
    Ok(bazaar::groupcompress::delta::decode_base128_int(&value))
}

#[pyfunction]
fn apply_delta(py: Python, basis: Vec<u8>, delta: Vec<u8>) -> PyResult<&PyBytes> {
    bazaar::groupcompress::delta::apply_delta(&basis, &delta)
        .map_err(|e| PyErr::new::<PyValueError, _>(format!("Invalid delta: {}", e)))
        .map(|x| PyBytes::new(py, &x))
}

#[pyfunction]
fn decode_copy_instruction(data: Vec<u8>, cmd: u8, pos: usize) -> PyResult<(usize, usize, usize)> {
    let ret = bazaar::groupcompress::delta::decode_copy_instruction(&data, cmd, pos);
    if ret.is_err() {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "Invalid copy instruction",
        ));
    }
    let ret = ret.unwrap();

    Ok((ret.0, ret.1, ret.2))
}

#[pyfunction]
fn apply_delta_to_source(
    py: Python,
    source: &[u8],
    delta_start: usize,
    delta_end: usize,
) -> PyResult<PyObject> {
    bazaar::groupcompress::delta::apply_delta_to_source(source, delta_start, delta_end)
        .map_err(|e| PyErr::new::<PyValueError, _>(format!("Invalid delta: {}", e)))
        .map(|x| PyBytes::new(py, &x).to_object(py))
}

#[pyfunction]
fn encode_copy_instruction(py: Python, offset: usize, length: usize) -> PyResult<PyObject> {
    let ret = bazaar::groupcompress::delta::encode_copy_instruction(offset, length);
    Ok(PyBytes::new(py, &ret).to_object(py))
}

#[pyfunction]
fn make_line_delta(py: Python, source_bytes: &[u8], target_bytes: &[u8]) -> Py<PyBytes> {
    PyBytes::new(
        py,
        bazaar::groupcompress::line_delta::make_delta(source_bytes, target_bytes)
            .flat_map(|x| x.into_owned())
            .collect::<Vec<_>>()
            .as_slice(),
    )
    .into_py(py)
}

#[pyfunction]
fn make_rabin_delta(py: Python, source_bytes: &[u8], target_bytes: &[u8]) -> Py<PyBytes> {
    PyBytes::new(
        py,
        bazaar::groupcompress::rabin_delta::make_delta(source_bytes, target_bytes).as_slice(),
    )
    .into_py(py)
}

#[pyclass]
pub struct LinesDeltaIndex(bazaar::groupcompress::line_delta::LinesDeltaIndex);

#[pymethods]
impl LinesDeltaIndex {
    #[new]
    fn new(lines: Vec<Vec<u8>>) -> Self {
        let index = bazaar::groupcompress::line_delta::LinesDeltaIndex::new(lines);
        Self(index)
    }

    #[getter]
    fn lines(&self, py: Python) -> Vec<PyObject> {
        self.0
            .lines()
            .iter()
            .map(|x| PyBytes::new(py, x.as_ref()).to_object(py))
            .collect()
    }

    fn make_delta<'a>(
        &'a self,
        py: Python,
        source: Vec<std::borrow::Cow<'a, [u8]>>,
        bytes_length: usize,
        soft: Option<bool>,
    ) -> (Vec<Py<PyBytes>>, Vec<bool>) {
        let (delta, index) = self.0.make_delta(source.as_slice(), bytes_length, soft);
        (
            delta
                .into_iter()
                .map(|x| PyBytes::new(py, x.as_ref()).into_py(py))
                .collect(),
            index,
        )
    }

    fn extend_lines(&mut self, lines: Vec<Vec<u8>>, index: Vec<bool>) -> PyResult<()> {
        self.0.extend_lines(lines.as_slice(), index.as_slice());
        Ok(())
    }

    #[getter]
    fn endpoint(&self) -> usize {
        self.0.endpoint()
    }
}

#[pyclass(unsendable)]
struct GroupCompressBlock(bazaar::groupcompress::block::GroupCompressBlock);

#[pymethods]
impl GroupCompressBlock {
    #[new]
    fn new() -> Self {
        Self(bazaar::groupcompress::block::GroupCompressBlock::new())
    }

    fn __len__(&self) -> usize {
        self.0.len()
    }

    #[getter]
    fn _z_content(&mut self, py: Python) -> PyResult<PyObject> {
        let ret = self.0.z_content();
        Ok(PyBytes::new(py, &ret).to_object(py))
    }

    #[getter]
    fn _content(&mut self, py: Python) -> PyResult<Option<PyObject>> {
        let ret = self.0.content();
        Ok(ret.map(|x| PyBytes::new(py, x).to_object(py)))
    }

    #[getter]
    fn _content_length(&self) -> Option<usize> {
        self.0.content_length()
    }

    #[classmethod]
    fn from_bytes(_type: &pyo3::types::PyType, data: &[u8]) -> PyResult<Self> {
        let ret = bazaar::groupcompress::block::GroupCompressBlock::from_bytes(data);
        if ret.is_err() {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                "Invalid block",
            ));
        }
        Ok(Self(ret.unwrap()))
    }

    fn extract(
        &mut self,
        py: Python,
        _key: PyObject,
        offset: usize,
        length: usize,
    ) -> PyResult<Vec<PyObject>> {
        let chunks = self
            .0
            .extract(offset, length)
            .map_err(|e| PyValueError::new_err(format!("Error during extract: {:?}", e)))?;
        Ok(chunks
            .into_iter()
            .map(|x| PyBytes::new(py, x.as_ref()).to_object(py))
            .collect())
    }

    fn set_chunked_content(&mut self, data: Vec<Vec<u8>>, length: usize) -> PyResult<()> {
        self.0.set_chunked_content(data.as_slice(), length);
        Ok(())
    }

    fn to_chunks(
        &mut self,
        py: Python,
        kind: Option<bazaar::groupcompress::block::CompressorKind>,
    ) -> (usize, Vec<PyObject>) {
        let (size, chunks) = self.0.to_chunks(kind);

        let chunks = chunks
            .into_iter()
            .map(|x| PyBytes::new(py, x.as_ref()).to_object(py))
            .collect();

        (size, chunks)
    }

    fn to_bytes(&mut self, py: Python) -> PyResult<PyObject> {
        let ret = self.0.to_bytes();
        Ok(PyBytes::new(py, &ret).to_object(py))
    }

    fn _ensure_content(&mut self, size: Option<usize>) -> PyResult<()> {
        self.0.ensure_content(size);
        Ok(())
    }

    fn _dump(&mut self, py: Python, include_text: Option<bool>) -> PyResult<PyObject> {
        let ret = self
            .0
            .dump(include_text)
            .map_err(|e| PyValueError::new_err(format!("Error during dump: {:?}", e)))?;

        Ok(ret
            .into_iter()
            .map(|x| match x {
                bazaar::groupcompress::block::DumpInfo::Fulltext(text) => (
                    PyBytes::new(py, b"f"),
                    text.map(|x| PyBytes::new(py, x.as_ref()).to_object(py)),
                )
                    .to_object(py),
                bazaar::groupcompress::block::DumpInfo::Delta(decomp_len, info) => (
                    PyBytes::new(py, b"d"),
                    decomp_len,
                    info.into_iter()
                        .map(|x| match x {
                            bazaar::groupcompress::block::DeltaInfo::Copy(offset, len, text) => (
                                offset,
                                len,
                                text.map(|x| PyBytes::new(py, x.as_ref()).to_object(py)),
                            )
                                .into_py(py),
                            bazaar::groupcompress::block::DeltaInfo::Insert(len, data) => (
                                len,
                                data.map(|x| PyBytes::new(py, x.as_slice()).to_object(py)),
                            )
                                .to_object(py),
                        })
                        .collect::<Vec<_>>()
                        .into_py(py),
                )
                    .into_py(py),
            })
            .collect::<Vec<_>>()
            .into_py(py))
    }
}

#[pyclass]
struct TraditionalGroupCompressor(bazaar::groupcompress::compressor::TraditionalGroupCompressor);

#[pymethods]
impl TraditionalGroupCompressor {
    #[new]
    fn new() -> Self {
        Self(bazaar::groupcompress::compressor::TraditionalGroupCompressor::new())
    }

    #[getter]
    fn chunks(&self, py: Python) -> Vec<PyObject> {
        self.0
            .chunks()
            .iter()
            .map(|x| PyBytes::new(py, x.as_ref()).to_object(py))
            .collect()
    }

    #[getter]
    fn endpoint(&self) -> usize {
        self.0.endpoint()
    }

    fn ratio(&self) -> f32 {
        self.0.ratio()
    }

    fn extract(&self, py: Python, key: Vec<Vec<u8>>) -> PyResult<(Vec<PyObject>, PyObject)> {
        let (data, hash) = self
            .0
            .extract(&key)
            .map_err(|e| PyValueError::new_err(format!("Error during extract: {:?}", e)))?;
        Ok((
            data.iter()
                .map(|x| PyBytes::new(py, x.as_ref()).to_object(py))
                .collect(),
            PyBytes::new(py, hash.as_bytes()).to_object(py),
        ))
    }

    fn compress(
        &mut self,
        py: Python,
        key: Key,
        chunks: Vec<Vec<u8>>,
        length: usize,
        expected_sha: Option<String>,
        nostore_sha: Option<String>,
        soft: Option<bool>,
    ) -> PyResult<(PyObject, usize, usize, &str)> {
        let chunks_l = chunks.iter().map(|x| x.as_slice()).collect::<Vec<_>>();
        self.0
            .compress(
                &key,
                chunks_l.as_slice(),
                length,
                expected_sha,
                nostore_sha,
                soft,
            )
            .map_err(|e| PyValueError::new_err(format!("Error during compress: {:?}", e)))
            .map(|(hash, size, chunks, kind)| {
                (
                    PyBytes::new(py, hash.as_ref()).to_object(py),
                    size,
                    chunks,
                    kind,
                )
            })
    }
}

#[pyfunction]
fn rabin_hash(data: Vec<u8>) -> PyResult<u32> {
    Ok(bazaar::groupcompress::rabin_delta::rabin_hash(
        data.try_into()
            .map_err(|e| PyValueError::new_err(format!("Error during rabin_hash: {:?}", e)))?,
    )
    .into())
}

pub(crate) fn _groupcompress_rs(py: Python) -> PyResult<&PyModule> {
    let m = PyModule::new(py, "groupcompress")?;
    m.add_wrapped(wrap_pyfunction!(encode_base128_int))?;
    m.add_wrapped(wrap_pyfunction!(decode_base128_int))?;
    m.add_wrapped(wrap_pyfunction!(apply_delta))?;
    m.add_wrapped(wrap_pyfunction!(decode_copy_instruction))?;
    m.add_wrapped(wrap_pyfunction!(encode_copy_instruction))?;
    m.add_wrapped(wrap_pyfunction!(apply_delta_to_source))?;
    m.add_wrapped(wrap_pyfunction!(make_line_delta))?;
    m.add_wrapped(wrap_pyfunction!(make_rabin_delta))?;
    m.add_wrapped(wrap_pyfunction!(rabin_hash))?;
    m.add_class::<LinesDeltaIndex>()?;
    m.add_class::<TraditionalGroupCompressor>()?;
    m.add(
        "NULL_SHA1",
        pyo3::types::PyBytes::new(py, &bazaar::groupcompress::NULL_SHA1),
    )?;
    Ok(m)
}
