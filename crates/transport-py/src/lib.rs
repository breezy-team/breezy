use breezy_transport::{Error, ReadStream, Result, Stat, UrlFragment, WriteStream};
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyIterator;
use pyo3::types::{PyBytes, PyList, PyType};
use pyo3_file::PyFileLikeObject;
use std::collections::HashMap;
use std::fs::{Metadata, Permissions};
use std::io::{BufRead, BufReader, Seek};
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use url::Url;

import_exception!(breezy.errors, TransportError);
import_exception!(breezy.errors, NoSmartMedium);
import_exception!(breezy.errors, NotLocalUrl);
import_exception!(breezy.errors, InProcessTransport);
import_exception!(breezy.transport, NoSuchFile);
import_exception!(breezy.transport, FileExists);
import_exception!(breezy.errors, PathNotChild);
import_exception!(breezy.errors, PermissionDenied);
import_exception!(breezy.errors, TransportNotPossible);
import_exception!(breezy.errors, ShortReadvError);

create_exception!(_transport_rs, UrlError, TransportError);

#[pyclass(subclass)]
struct Transport(Box<dyn breezy_transport::Transport>);

fn map_transport_err_to_py_err(e: Error, t: Option<PyObject>, p: Option<&UrlFragment>) -> PyErr {
    match e {
        Error::InProcessTransport => InProcessTransport::new_err(()),
        Error::NotLocalUrl(url) => NotLocalUrl::new_err((url,)),
        Error::NoSmartMedium => NoSmartMedium::new_err((t.unwrap(),)),
        Error::NoSuchFile(name) => NoSuchFile::new_err((name,)),
        Error::FileExists(name) => FileExists::new_err((name,)),
        Error::TransportNotPossible => TransportNotPossible::new_err(()),
        Error::UrlError(e) => UrlError::new_err(e.to_string()),
        Error::PermissionDenied(name) => PermissionDenied::new_err((name,)),
        Error::PathNotChild => PathNotChild::new_err(()),
        Error::UrlutilsError(e) => UrlError::new_err(format!("{:?}", e)),
        Error::Io(e) => e.into(),
        Error::UnexpectedEof => PyValueError::new_err("Unexpected EOF"),
        Error::ShortReadvError(path, offset, expected, got) => {
            ShortReadvError::new_err((path, offset, expected, got))
        }
    }
}

#[cfg(unix)]
fn perms_from_py_object(obj: PyObject) -> Permissions {
    Python::with_gil(|py| {
        let mode = obj.extract::<u32>(py).unwrap();
        Permissions::from_mode(mode)
    })
}

#[pyclass]
struct PyStat {
    #[pyo3(get)]
    st_mode: u32,

    #[pyo3(get)]
    st_size: usize,
}

trait BufReadStream: BufRead + Seek {}

impl BufReadStream for BufReader<Box<dyn ReadStream + Sync + Send>> {}

#[pyclass]
struct PyBufReadStream(Box<dyn BufReadStream + Sync + Send>);

#[pyclass]
struct PyWriteStream(Box<dyn WriteStream + Sync + Send>);

#[pymethods]
impl PyWriteStream {
    fn write(&mut self, data: &PyBytes) -> PyResult<usize> {
        self.0.write(data.as_bytes()).map_err(|e| e.into())
    }

    fn close(&mut self, want_fdatasync: Option<bool>) -> PyResult<()> {
        if want_fdatasync.unwrap_or(false) {
            self.fdatasync()?;
        }
        Ok(())
    }

    fn fdatasync(&mut self) -> PyResult<()> {
        self.0.sync_all().map_err(|e| e.into())
    }
}

impl PyBufReadStream {
    fn new(read: Box<dyn ReadStream + Sync + Send>) -> Self {
        Self(Box::new(BufReader::new(read)))
    }
}

#[pymethods]
impl PyBufReadStream {
    fn read(&mut self, py: Python, size: Option<usize>) -> PyResult<PyObject> {
        let mut buf = vec![0; size.unwrap_or(4096)];
        let ret = self.0.read(&mut buf)?;
        Ok(PyBytes::new(py, &buf[..ret]).to_object(py).to_object(py))
    }

    fn seek(&mut self, offset: i64, whence: i8) -> PyResult<u64> {
        let seekfrom = match whence {
            0 => std::io::SeekFrom::Start(offset as u64),
            1 => std::io::SeekFrom::Current(offset),
            2 => std::io::SeekFrom::End(offset),
            _ => return Err(PyValueError::new_err("Invalid whence")),
        };

        self.0.seek(seekfrom).map_err(|e| e.into())
    }

    fn tell(&mut self) -> PyResult<u64> {
        self.0.stream_position().map_err(|e| e.into())
    }

    fn readline(&mut self, py: Python) -> PyResult<PyObject> {
        let mut buf = vec![];
        let ret = self.0.read_until(b'\n', &mut buf)?;
        buf.truncate(ret);
        Ok(PyBytes::new(py, &buf).to_object(py).to_object(py))
    }

    fn __next__(&mut self, py: Python) -> PyResult<Option<PyObject>> {
        let mut buf = vec![];
        let ret = self.0.read_until(b'\n', &mut buf)?;
        if ret == 0 {
            return Ok(None);
        }
        buf.truncate(ret);
        Ok(Some(PyBytes::new(py, &buf).to_object(py).to_object(py)))
    }

    fn close(&mut self) -> PyResult<()> {
        Ok(())
    }

    fn __enter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __exit__(
        &self,
        _exc_type: Option<&PyType>,
        _exc_val: Option<&PyAny>,
        _exc_tb: Option<&PyAny>,
    ) -> PyResult<bool> {
        Ok(true)
    }
}

impl Transport {
    fn map_to_py_err(slf: &PyCell<Self>, py: Python, e: Error, p: Option<&str>) -> PyErr {
        let obj = slf.borrow().into_py(py);
        map_transport_err_to_py_err(e, Some(obj), p)
    }
}

#[pymethods]
impl Transport {
    fn external_url(&self) -> PyResult<String> {
        Ok(self
            .0
            .external_url()
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?
            .to_string())
    }

    fn get_bytes(&self, py: Python, path: &str) -> PyResult<PyObject> {
        let ret = self
            .0
            .get_bytes(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(PyBytes::new(py, &ret).to_object(py).to_object(py))
    }

    #[getter]
    fn base(&self) -> PyResult<String> {
        Ok(self.0.base().to_string())
    }

    fn has(&self, path: &str) -> PyResult<bool> {
        self.0
            .has(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn has_any(&self, paths: Vec<&str>) -> PyResult<bool> {
        self.0
            .has_any(paths.as_slice())
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn mkdir(&self, path: &str, mode: Option<PyObject>) -> PyResult<()> {
        self.0
            .mkdir(path, mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(())
    }

    fn ensure_base(&self, mode: Option<PyObject>) -> PyResult<bool> {
        self.0
            .ensure_base(mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn local_abspath(&self, py: Python, path: &str) -> PyResult<PathBuf> {
        self.0
            .local_abspath(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn get(slf: PyRef<Self>, py: Python, path: &str) -> PyResult<PyObject> {
        let ret = slf
            .0
            .get(path)
            .map_err(|e| map_transport_err_to_py_err(e, Some(slf.into_py(py)), None))?;
        Ok(PyBufReadStream::new(ret).into_py(py))
    }

    fn get_smart_medium(slf: &PyCell<Self>, py: Python) -> PyResult<PyObject> {
        slf.borrow()
            .0
            .get_smart_medium()
            .map_err(|e| Transport::map_to_py_err(slf, py, e, None))?;
        // TODO(jelmer)
        Ok(py.None())
    }

    fn stat(&self, py: Python, path: &str) -> PyResult<PyObject> {
        let stat = self
            .0
            .stat(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(PyStat {
            st_size: stat.size,
            st_mode: stat.mode,
        }
        .into_py(py))
    }

    fn clone(&self, py: Python, offset: Option<PyObject>) -> PyResult<Self> {
        let inner = if let Some(offset) = offset {
            let offset = offset.extract::<&str>(py)?;
            self.0.clone(Some(offset))
        } else {
            self.0.clone(None)
        }
        .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(Transport(inner))
    }

    fn relpath(&self, path: &str) -> PyResult<String> {
        let url = Url::parse(path).map_err(|_| PyValueError::new_err((path.to_string(),)))?;
        self.0
            .relpath(&url)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn abspath(&self, path: &str) -> PyResult<String> {
        Ok(self
            .0
            .abspath(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?
            .to_string())
    }

    fn put_bytes(&self, path: &str, data: &[u8], mode: Option<PyObject>) -> PyResult<()> {
        self.0
            .put_bytes(path, data, mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(())
    }

    fn put_bytes_non_atomic(
        &self,
        path: &str,
        data: &[u8],
        mode: Option<PyObject>,
        create_parent_dir: Option<bool>,
        dir_permissions: Option<PyObject>,
    ) -> PyResult<()> {
        self.0
            .put_bytes_non_atomic(
                path,
                data,
                mode.map(perms_from_py_object),
                create_parent_dir,
                dir_permissions.map(perms_from_py_object),
            )
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(())
    }

    fn put_file(&self, path: &str, file: PyObject, mode: Option<PyObject>) -> PyResult<()> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        self.0
            .put_file(path, &mut file, mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(())
    }

    fn put_file_non_atomic(
        &self,
        path: &str,
        file: PyObject,
        mode: Option<PyObject>,
        create_parent_dir: Option<bool>,
        dir_permissions: Option<PyObject>,
    ) -> PyResult<()> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        self.0
            .put_file_non_atomic(
                path,
                &mut file,
                mode.map(perms_from_py_object),
                create_parent_dir,
                dir_permissions.map(perms_from_py_object),
            )
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(())
    }

    fn delete(&self, path: &str) -> PyResult<()> {
        self.0
            .delete(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(())
    }

    fn rmdir(&self, path: &str) -> PyResult<()> {
        self.0
            .rmdir(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(())
    }

    fn rename(&self, from: &str, to: &str) -> PyResult<()> {
        self.0
            .rename(from, to)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(())
    }

    fn set_segment_parameter(&mut self, name: &str, value: Option<&str>) -> PyResult<()> {
        self.0
            .set_segment_parameter(name, value)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(())
    }

    fn get_segment_parameters(&self) -> PyResult<HashMap<String, String>> {
        self.0
            .get_segment_parameters()
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn create_prefix(&self, mode: Option<PyObject>) -> PyResult<()> {
        self.0
            .create_prefix(mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn lock_write(&self, path: &str) -> PyResult<Lock> {
        self.0
            .lock_write(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
            .map(Lock::from)
    }

    fn lock_read(&self, path: &str) -> PyResult<Lock> {
        self.0
            .lock_read(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
            .map(Lock::from)
    }

    fn recommended_page_size(&self) -> usize {
        self.0.recommended_page_size()
    }

    fn is_readonly(&self) -> bool {
        self.0.is_readonly()
    }

    fn readv(
        &self,
        py: Python,
        path: &str,
        offsets: Vec<(u64, usize)>,
        adjust_for_latency: Option<bool>,
        upper_limit: Option<u64>,
    ) -> PyResult<PyObject> {
        let buffered = self
            .0
            .readv(
                path,
                offsets,
                adjust_for_latency.unwrap_or(false),
                upper_limit,
            )
            .map(|r| {
                r.map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
                    .map(|(o, r)| (o, PyBytes::new(py, &r).into_py(py)))
            })
            .collect::<PyResult<Vec<(u64, PyObject)>>>()?;
        let list = PyList::new(py, &buffered);
        Ok(PyIterator::from_object(py, list)?.to_object(py))
    }

    fn listable(&self) -> bool {
        self.0.listable()
    }

    fn list_dir(&self, path: &str) -> PyResult<Vec<String>> {
        self.0
            .list_dir(path)
            .map(|r| r.map_err(|e| map_transport_err_to_py_err(e, None, None)))
            .collect::<PyResult<Vec<_>>>()
    }

    fn append_bytes(&self, path: &str, bytes: &[u8], mode: Option<PyObject>) -> PyResult<()> {
        self.0
            .append_bytes(path, bytes, mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn append_file(&self, path: &str, file: PyObject, mode: Option<PyObject>) -> PyResult<()> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        self.0
            .append_file(path, &mut file, mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn iter_files_recursive(&self, py: Python) -> PyResult<PyObject> {
        let iter = self.0.iter_files_recursive().map(|r| {
            r.map_err(|e| map_transport_err_to_py_err(e, None, None))
                .map(|o| o.to_object(py))
        });
        iter.collect::<PyResult<Vec<_>>>().map(|v| v.to_object(py))
    }

    fn open_write_stream(
        slf: &PyCell<Self>,
        py: Python,
        path: &str,
        mode: Option<PyObject>,
    ) -> PyResult<PyWriteStream> {
        slf.borrow()
            .0
            .open_write_stream(path, mode.map(perms_from_py_object))
            .map_err(|e| Transport::map_to_py_err(slf, py, e, None))
            .map(|w| PyWriteStream(w))
    }

    fn delete_tree(&self, path: &str) -> PyResult<()> {
        self.0
            .delete_tree(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn r#move(&self, from: &str, to: &str) -> PyResult<()> {
        self.0
            .r#move(from, to)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn copy_tree(&self, from: &str, to: &str) -> PyResult<()> {
        self.0
            .copy_tree(from, to)
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn copy_tree_to_transport(&self, to_transport: &Transport) -> PyResult<()> {
        self.0
            .copy_tree_to_transport(to_transport.0.as_ref())
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn copy_to(
        &self,
        relpaths: Vec<&str>,
        to_transport: &Transport,
        mode: Option<PyObject>,
    ) -> PyResult<()> {
        self.0
            .copy_to(
                relpaths.as_slice(),
                to_transport.0.as_ref(),
                mode.map(perms_from_py_object),
            )
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    #[getter]
    fn _can_roundtrip_unix_modebits(&self) -> bool {
        self.0.can_roundtrip_unix_modebits()
    }
}

#[pyclass]
struct Lock(Box<dyn breezy_transport::Lock + Send + Sync>);

impl From<Box<dyn breezy_transport::Lock + Send + Sync>> for Lock {
    fn from(lock: Box<dyn breezy_transport::Lock + Send + Sync>) -> Self {
        Lock(lock)
    }
}

#[pymethods]
impl Lock {
    fn unlock(&mut self) -> PyResult<()> {
        self.0
            .unlock()
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }
}

#[pyclass(extends=Transport)]
struct LocalTransport {}

#[pymethods]
impl LocalTransport {
    #[new]
    fn new(url: &str) -> PyResult<(Self, Transport)> {
        let url = Url::parse(url).map_err(|e| PyValueError::new_err(e.to_string()))?;
        Ok((
            LocalTransport {},
            Transport(Box::new(breezy_transport::local::LocalTransport::from(url))),
        ))
    }
}

#[pyfunction]
fn get_test_permutations(py: Python) -> PyResult<PyObject> {
    let test_server_module = py.import("breezy.tests.test_server")?.to_object(py);
    let local_url_server = test_server_module.getattr(py, "LocalURLServer")?;
    let local_transport = py
        .import("breezy.transport.local")?
        .getattr("LocalTransport")?;
    let ret = PyList::empty(py);
    ret.append((local_transport, local_url_server))?;
    Ok(ret.to_object(py))
}

#[pymodule]
fn _transport_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<Transport>()?;
    m.add_class::<LocalTransport>()?;
    m.add_function(wrap_pyfunction!(get_test_permutations, m)?)?;
    Ok(())
}
