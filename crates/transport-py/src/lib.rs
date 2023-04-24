use breezy_transport::{
    Error, ReadStream, Result, Stat, Transport as TransportTrait, UrlFragment, WriteStream,
};
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyIterator, PyList, PyType};
use pyo3_file::PyFileLikeObject;
use std::collections::HashMap;
use std::fs::{Metadata, Permissions};
use std::io::{BufRead, BufReader, Read, Seek};
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
import_exception!(breezy.errors, LockContention);
import_exception!(breezy.errors, LockFailed);
import_exception!(breezy.errors, ReadError);
import_exception!(breezy.errors, PathError);
import_exception!(breezy.errors, DirectoryNotEmpty);
import_exception!(breezy.errors, NotADirectory);
import_exception!(breezy.urlutils, InvalidURL);

#[pyclass(subclass)]
struct Transport(Box<dyn breezy_transport::Transport>);

fn map_transport_err_to_py_err(e: Error, t: Option<PyObject>, p: Option<&UrlFragment>) -> PyErr {
    let pick_path = |n: Option<String>| {
        if n.is_none() {
            n
        } else {
            p.map(|p| p.to_string())
        }
    };
    match e {
        Error::InProcessTransport => InProcessTransport::new_err(()),
        Error::NotLocalUrl(url) => NotLocalUrl::new_err((url,)),
        Error::NoSmartMedium => NoSmartMedium::new_err((t.unwrap(),)),
        Error::NoSuchFile(name) => NoSuchFile::new_err((pick_path(name),)),
        Error::FileExists(name) => FileExists::new_err((pick_path(name),)),
        Error::TransportNotPossible => TransportNotPossible::new_err(()),
        Error::UrlError(e) => InvalidURL::new_err((p.map(|p| p.to_string()),)),
        Error::PermissionDenied(name) => PermissionDenied::new_err((pick_path(name),)),
        Error::PathNotChild => PathNotChild::new_err(()),
        Error::UrlutilsError(e) => InvalidURL::new_err((p.map(|p| p.to_string()),)),
        Error::Io(e) => e.into(),
        Error::UnexpectedEof => PyValueError::new_err("Unexpected EOF"),
        Error::LockContention(name) => LockContention::new_err((name,)),
        Error::LockFailed(name, error) => LockFailed::new_err((name, error)),
        Error::NotADirectoryError(name) => NoSuchFile::new_err((pick_path(name),)),
        Error::IsADirectoryError(name) => ReadError::new_err((pick_path(name), "is a directory")),
        Error::DirectoryNotEmptyError(name) => DirectoryNotEmpty::new_err((pick_path(name),)),
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

    #[pyo3(get)]
    st_mtime: Option<f64>,
}

trait BufReadStream: BufRead + Seek {}

impl BufReadStream for BufReader<Box<dyn ReadStream + Sync + Send>> {}

#[pyclass]
struct PyBufReadStream {
    f: Box<dyn BufReadStream + Sync + Send>,
    path: String,
}

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

    fn __enter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __exit__(
        &self,
        _exc_type: Option<&PyType>,
        _exc_val: Option<&PyAny>,
        _exc_tb: Option<&PyAny>,
    ) -> PyResult<bool> {
        Ok(false)
    }

    fn flush(&mut self) -> PyResult<()> {
        self.0.flush().map_err(|e| e.into())
    }
}

impl PyBufReadStream {
    fn new(read: Box<dyn ReadStream + Sync + Send>, path: &str) -> Self {
        Self {
            f: Box::new(BufReader::new(read)),
            path: path.to_string(),
        }
    }

    fn map_io_err_to_py_err(&self, e: std::io::Error) -> PyErr {
        let transport_err = breezy_transport::map_io_err_to_transport_err(e, Some(&self.path));
        map_transport_err_to_py_err(transport_err, None, Some(self.path.as_str()))
    }
}

#[pymethods]
impl PyBufReadStream {
    fn read(&mut self, py: Python, size: Option<usize>) -> PyResult<PyObject> {
        if let Some(size) = size {
            let mut buf = vec![0; size];
            let ret = self
                .f
                .read(&mut buf)
                .map_err(|e| self.map_io_err_to_py_err(e))?;
            Ok(PyBytes::new(py, &buf[..ret]).to_object(py))
        } else {
            let mut buf = Vec::new();
            self.f.read_to_end(&mut buf)
                .map_err(|e| self.map_io_err_to_py_err(e))?;
            Ok(PyBytes::new(py, &buf).to_object(py))
        }
    }

    fn seek(&mut self, offset: i64, whence: Option<i8>) -> PyResult<u64> {
        let seekfrom = match whence.unwrap_or(0) {
            0 => std::io::SeekFrom::Start(offset as u64),
            1 => std::io::SeekFrom::Current(offset),
            2 => std::io::SeekFrom::End(offset),
            _ => return Err(PyValueError::new_err("Invalid whence")),
        };

        self.f
            .seek(seekfrom)
            .map_err(|e| self.map_io_err_to_py_err(e))
    }

    fn tell(&mut self) -> PyResult<u64> {
        self.f
            .stream_position()
            .map_err(|e| self.map_io_err_to_py_err(e))
    }

    fn readline(&mut self, py: Python) -> PyResult<PyObject> {
        let mut buf = vec![];
        let ret = self
            .f
            .read_until(b'\n', &mut buf)
            .map_err(|e| self.map_io_err_to_py_err(e))?;
        buf.truncate(ret);
        Ok(PyBytes::new(py, &buf).to_object(py).to_object(py))
    }

    fn __iter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __next__(&mut self, py: Python) -> PyResult<Option<PyObject>> {
        let mut buf = vec![];
        let ret = self
            .f
            .read_until(b'\n', &mut buf)
            .map_err(|e| self.map_io_err_to_py_err(e))?;
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
        Ok(false)
    }

    fn readlines(&mut self, py: Python) -> PyResult<PyObject> {
        let ret = PyList::empty(py);
        while let Some(line) = self.__next__(py)? {
            ret.append(line)?;
        }
        Ok(ret.to_object(py))
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

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!("{:?}", self.0))
    }

    fn get_bytes(slf: &PyCell<Self>, py: Python, path: &str) -> PyResult<PyObject> {
        let ret = slf.borrow().0.get_bytes(path).map_err(|e| match e {
            Error::IsADirectoryError(_) => {
                ReadError::new_err((path.to_string(), "Is a directory".to_string()))
            }
            Error::NotADirectoryError(_) => {
                NoSuchFile::new_err((path.to_string(), "Not a directory".to_string()))
            }
            e => map_transport_err_to_py_err(e, Some(slf.into_py(py)), Some(path)),
        })?;

        Ok(PyBytes::new(py, &ret).to_object(py).to_object(py))
    }

    #[getter]
    fn base(&self) -> PyResult<String> {
        Ok(self.0.base().to_string())
    }

    fn has(&self, path: &str) -> PyResult<bool> {
        self.0
            .has(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    fn has_any(&self, paths: Vec<&str>) -> PyResult<bool> {
        self.0
            .has_any(paths.as_slice())
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn mkdir(slf: &PyCell<Self>, py: Python, path: &str, mode: Option<PyObject>) -> PyResult<()> {
        slf.borrow()
            .0
            .mkdir(path, mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, Some(slf.into_py(py)), Some(path)))?;
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
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    fn get(slf: PyRef<Self>, py: Python, path: &str) -> PyResult<PyObject> {
        let ret = slf.0.get(path).map_err(|e| match e {
            Error::IsADirectoryError(_) => {
                ReadError::new_err((path.to_string(), "Is a directory".to_string()))
            }
            Error::NotADirectoryError(_) => {
                NoSuchFile::new_err((path.to_string(), "Not a directory".to_string()))
            }
            e => map_transport_err_to_py_err(e, Some(slf.into_py(py)), Some(path)),
        })?;
        Ok(PyBufReadStream::new(ret, path).into_py(py))
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
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))?;
        Ok(PyStat {
            st_size: stat.size,
            st_mode: stat.mode,
            st_mtime: stat.mtime,
        }
        .into_py(py))
    }

    fn relpath(&self, path: Option<&str>) -> PyResult<String> {
        let path = path.unwrap_or(".");
        let url = Url::parse(path).map_err(|_| PyValueError::new_err((path.to_string(),)))?;
        self.0
            .relpath(&url)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    fn abspath(&self, path: &str) -> PyResult<String> {
        Ok(self
            .0
            .abspath(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))?
            .to_string())
    }

    fn put_bytes(
        slf: &PyCell<Self>,
        py: Python,
        path: &str,
        data: &[u8],
        mode: Option<PyObject>,
    ) -> PyResult<()> {
        slf.borrow()
            .0
            .put_bytes(path, data, mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, Some(slf.into_py(py)), Some(path)))?;
        Ok(())
    }

    fn put_bytes_non_atomic(
        slf: &PyCell<Self>,
        py: Python,
        path: &str,
        data: &[u8],
        mode: Option<PyObject>,
        create_parent_dir: Option<bool>,
        dir_mode: Option<PyObject>,
    ) -> PyResult<()> {
        slf.borrow()
            .0
            .put_bytes_non_atomic(
                path,
                data,
                mode.map(perms_from_py_object),
                create_parent_dir,
                dir_mode.map(perms_from_py_object),
            )
            .map_err(|e| map_transport_err_to_py_err(e, Some(slf.into_py(py)), Some(path)))?;
        Ok(())
    }

    fn put_file(
        slf: &PyCell<Self>,
        py: Python,
        path: &str,
        file: PyObject,
        mode: Option<PyObject>,
    ) -> PyResult<u64> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        let ret = slf
            .borrow()
            .0
            .put_file(path, &mut file, mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, Some(slf.into_py(py)), Some(path)))?;
        Ok(ret)
    }

    fn put_file_non_atomic(
        slf: &PyCell<Self>,
        py: Python,
        path: &str,
        file: PyObject,
        mode: Option<PyObject>,
        create_parent_dir: Option<bool>,
        dir_mode: Option<PyObject>,
    ) -> PyResult<()> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        slf.borrow()
            .0
            .put_file_non_atomic(
                path,
                &mut file,
                mode.map(perms_from_py_object),
                create_parent_dir,
                dir_mode.map(perms_from_py_object),
            )
            .map_err(|e| map_transport_err_to_py_err(e, Some(slf.into_py(py)), Some(path)))?;
        Ok(())
    }

    fn delete(&self, path: &str) -> PyResult<()> {
        self.0
            .delete(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))?;
        Ok(())
    }

    fn rmdir(&self, path: &str) -> PyResult<()> {
        self.0
            .rmdir(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))?;
        Ok(())
    }

    fn rename(&self, from: &str, to: &str) -> PyResult<()> {
        self.0
            .rename(from, to)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))?;
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
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
            .map(Lock::from)
    }

    fn lock_read(&self, path: &str) -> PyResult<Lock> {
        self.0
            .lock_read(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
            .map(Lock::from)
    }

    fn recommended_page_size(&self) -> usize {
        self.0.recommended_page_size()
    }

    fn is_readonly(&self) -> bool {
        self.0.is_readonly()
    }

    fn _readv(
        slf: &PyCell<Self>,
        py: Python,
        path: &str,
        offsets: Vec<(usize, usize)>,
        max_readv_combine: Option<usize>,
        bytes_to_read_before_seek: Option<usize>,
    ) -> PyResult<PyObject> {
        if offsets.is_empty() {
            return Ok(PyList::empty(py).into_py(py));
        }
        let ret = slf.borrow().0.get(path).map_err(|e| match e {
            Error::IsADirectoryError(_) => {
                ReadError::new_err((path.to_string(), "Is a directory".to_string()))
            }
            Error::NotADirectoryError(_) => {
                ReadError::new_err((path.to_string(), "Not a directory".to_string()))
            }
            e => map_transport_err_to_py_err(e, Some(slf.into_py(py)), Some(path)),
        })?;
        let f = PyBufReadStream::new(ret, path).into_py(py);
        let buffered = seek_and_read(
            py,
            f,
            offsets,
            max_readv_combine,
            bytes_to_read_before_seek,
            Some(path),
        )?;
        let list = PyList::new(py, &buffered);
        Ok(PyIterator::from_object(py, list)?.into_py(py))
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
            .map(|r| r.map_err(|e| map_transport_err_to_py_err(e, None, Some(path))))
            .collect::<PyResult<Vec<_>>>()
    }

    fn append_bytes(&self, path: &str, bytes: &[u8], mode: Option<PyObject>) -> PyResult<u64> {
        self.0
            .append_bytes(path, bytes, mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    fn append_file(&self, path: &str, file: PyObject, mode: Option<PyObject>) -> PyResult<u64> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        self.0
            .append_file(path, &mut file, mode.map(perms_from_py_object))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    fn iter_files_recursive(&self, py: Python) -> PyResult<PyObject> {
        let iter = self.0.iter_files_recursive().map(|r| {
            r.map_err(|e| map_transport_err_to_py_err(e, None, Some(".")))
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
            .map_err(|e| Transport::map_to_py_err(slf, py, e, Some(path)))
            .map(|w| PyWriteStream(w))
    }

    fn delete_tree(&self, path: &str) -> PyResult<()> {
        self.0
            .delete_tree(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    fn r#move(&self, from: &str, to: &str) -> PyResult<()> {
        self.0
            .r#move(from, to)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))
    }

    fn copy_tree(&self, from: &str, to: &str) -> PyResult<()> {
        self.0
            .copy_tree(from, to)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))
    }

    fn copy_tree_to_transport(&self, py: Python, to_transport: PyObject) -> PyResult<()> {
        if let Ok(t) = to_transport.clone_ref(py).extract::<PyRef<Transport>>(py) {
            self.0
                .copy_tree_to_transport(t.0.as_ref())
                .map_err(|e| map_transport_err_to_py_err(e, None, Some(".")))
        } else {
            let t = Box::new(breezy_transport::pyo3::PyTransport::from(to_transport));
            self.0
                .copy_tree_to_transport(t.as_ref())
                .map_err(|e| map_transport_err_to_py_err(e, None, Some(".")))
        }
    }

    fn hardlink(&self, from: &str, to: &str) -> PyResult<()> {
        self.0
            .hardlink(from, to)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))
    }

    fn symlink(&self, from: &str, to: &str) -> PyResult<()> {
        self.0
            .symlink(from, to)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))
    }

    fn readlink(&self, path: &str) -> PyResult<String> {
        self.0
            .readlink(path)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    fn copy_to(
        &self,
        py: Python,
        relpaths: PyObject,
        to_transport: PyObject,
        mode: Option<PyObject>,
    ) -> PyResult<usize> {
        let relpaths = relpaths.as_ref(py).iter()?.map(|o| o?.extract()).collect::<PyResult<Vec<_>>>()?;

        if let Ok(t) = to_transport.clone_ref(py).downcast::<PyCell<Transport>>(py) {
            self.0
                .copy_to(
                    relpaths.as_slice(),
                    t.borrow().0.as_ref(),
                    mode.map(perms_from_py_object),
                )
                .map_err(|e| map_transport_err_to_py_err(e, None, None))
        } else {
            let t = Box::new(breezy_transport::pyo3::PyTransport::from(to_transport));
            self.0
                .copy_to(
                    relpaths.as_slice(),
                    t.as_ref(),
                    mode.map(perms_from_py_object),
                )
                .map_err(|e| map_transport_err_to_py_err(e, None, None))
        }
    }

    fn _can_roundtrip_unix_modebits(&self) -> bool {
        self.0.can_roundtrip_unix_modebits()
    }

    fn copy(&self, from: &str, to: &str) -> PyResult<()> {
        self.0
            .copy(from, to)
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))
    }
}

#[pyclass]
struct Lock(Box<dyn breezy_transport::lock::Lock + Send + Sync>);

impl From<Box<dyn breezy_transport::lock::Lock + Send + Sync>> for Lock {
    fn from(lock: Box<dyn breezy_transport::lock::Lock + Send + Sync>) -> Self {
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

#[pyclass(extends=Transport,subclass)]
struct LocalTransport {}

#[pymethods]
impl LocalTransport {
    #[new]
    fn new(url: &str) -> PyResult<(Self, Transport)> {
        Ok((
            LocalTransport {},
            Transport(Box::new(
                breezy_transport::local::LocalTransport::new(url)
                    .map_err(|e| map_transport_err_to_py_err(e, None, None))?,
            )),
        ))
    }

    fn clone(slf: PyRef<Self>, py: Python, offset: Option<PyObject>) -> PyResult<PyObject> {
        let super_ = slf.as_ref();
        let inner = if let Some(offset) = offset {
            let offset = offset.extract::<&str>(py)?;
            super_.0.clone(Some(offset))
        } else {
            super_.0.clone(None)
        }
        .map_err(|e| map_transport_err_to_py_err(e, None, None))?;

        let init = PyClassInitializer::from(Transport(inner));
        let init = init.add_subclass(Self {});
        Ok(PyCell::new(py, init)?.to_object(py))
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

#[pyfunction]
fn coalesce_offsets(
    offsets: Vec<(usize, usize)>,
    mut limit: Option<usize>,
    mut fudge_factor: Option<usize>,
    mut max_size: Option<usize>,
) -> PyResult<Vec<(usize, usize, Vec<(usize, usize)>)>> {
    if limit == Some(0) {
        limit = None;
    }
    if fudge_factor == Some(0) {
        fudge_factor = None;
    }
    if max_size == Some(0) {
        max_size = None;
    }
    breezy_transport::readv::coalesce_offsets(offsets.as_slice(), limit, fudge_factor, max_size)
        .map_err(|e| PyValueError::new_err(format!("{}", e)))
}

const DEFAULT_MAX_READV_COMBINE: usize = 50;
const DEFAULT_BYTES_TO_READ_BEFORE_SEEK: usize = 0;

#[pyfunction]
fn seek_and_read(
    py: Python,
    file: PyObject,
    offsets: Vec<(usize, usize)>,
    max_readv_combine: Option<usize>,
    bytes_to_read_before_seek: Option<usize>,
    path: Option<&str>,
) -> PyResult<Vec<(usize, PyObject)>> {
    let f = PyFileLikeObject::with_requirements(file, true, false, true)?;
    let data = breezy_transport::readv::seek_and_read(
        f,
        offsets,
        max_readv_combine.unwrap_or(DEFAULT_MAX_READV_COMBINE),
        bytes_to_read_before_seek.unwrap_or(DEFAULT_BYTES_TO_READ_BEFORE_SEEK),
    )
    .map_err(|e| -> PyErr { e.into() })?;

    data.into_iter()
        .map(|e| {
            e.map(|(offset, data)| (offset, PyBytes::new(py, data.as_slice()).into()))
                .map_err(|(e, offset, length, actual)| match e.kind() {
                    std::io::ErrorKind::UnexpectedEof => ShortReadvError::new_err((
                        path.map(|p| p.to_string()),
                        offset,
                        length,
                        actual,
                    )),
                    _ => e.into(),
                })
        })
        .collect::<PyResult<Vec<_>>>()
}

#[pymodule]
fn _transport_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<Transport>()?;
    m.add_class::<LocalTransport>()?;
    m.add_function(wrap_pyfunction!(get_test_permutations, m)?)?;
    m.add_wrapped(wrap_pyfunction!(seek_and_read))?;
    m.add_wrapped(wrap_pyfunction!(coalesce_offsets))?;

    Ok(())
}
