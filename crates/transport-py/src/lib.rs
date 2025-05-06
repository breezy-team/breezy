use breezy_transport::lock::{FileLock, Lock as LockTrait, LockError};
use breezy_transport::{Error, ReadStream, Transport as TransportTrait, UrlFragment, WriteStream};
use log::debug;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyIterator, PyList, PyType};
use pyo3_filelike::PyBinaryFile;
use std::collections::HashMap;
use std::fs::Permissions;
use std::io::{BufRead, BufReader, Read, Seek, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
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
struct Transport(Box<dyn TransportTrait>);

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
        Error::UrlError(_e) => InvalidURL::new_err((p.map(|p| p.to_string()),)),
        Error::PermissionDenied(name) => PermissionDenied::new_err((pick_path(name),)),
        Error::PathNotChild => PathNotChild::new_err(()),
        Error::UrlutilsError(_e) => InvalidURL::new_err((p.map(|p| p.to_string()),)),
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

#[cfg(unix)]
fn default_perms() -> Permissions {
    use nix::sys::stat::{umask, Mode};
    let mask = umask(Mode::empty());
    umask(mask);
    let mode = 0o666 & !mask.bits();
    Permissions::from_mode(mode as u32)
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
    path: PathBuf,
}

#[pyclass]
struct PyWriteStream(Box<dyn WriteStream + Sync + Send>);

#[pymethods]
impl PyWriteStream {
    fn write(&mut self, py: Python, data: &[u8]) -> PyResult<usize> {
        py.allow_threads(|| self.0.write(data))
            .map_err(|e| e.into())
    }

    #[pyo3(signature = (want_fdatasync=None))]
    fn close(&mut self, py: Python, want_fdatasync: Option<bool>) -> PyResult<()> {
        if want_fdatasync.unwrap_or(false) {
            self.fdatasync(py)?;
        }
        Ok(())
    }

    fn fdatasync(&mut self, py: Python) -> PyResult<()> {
        py.allow_threads(|| self.0.sync_data())
            .map_err(|e| e.into())
    }

    fn __enter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __exit__(
        &self,
        _exc_type: Option<&Bound<PyType>>,
        _exc_val: Option<&Bound<PyAny>>,
        _exc_tb: Option<&Bound<PyAny>>,
    ) -> PyResult<bool> {
        Ok(false)
    }

    fn flush(&mut self, py: Python) -> PyResult<()> {
        py.allow_threads(|| self.0.flush()).map_err(|e| e.into())
    }

    fn writelines(&mut self, py: Python, lines: &Bound<PyList>) -> PyResult<()> {
        for line in lines.iter() {
            self.write(py, line.extract::<&[u8]>().unwrap())?;
        }
        Ok(())
    }
}

impl PyBufReadStream {
    fn new(read: Box<dyn ReadStream + Sync + Send>, path: &Path) -> Self {
        Self {
            f: Box::new(BufReader::new(read)),
            path: path.to_path_buf(),
        }
    }

    fn map_io_err_to_py_err(&self, e: std::io::Error) -> PyErr {
        let transport_err = breezy_transport::map_io_err_to_transport_err(
            e,
            Some(&self.path.as_path().to_string_lossy()),
        );
        map_transport_err_to_py_err(
            transport_err,
            None,
            Some(self.path.as_path().to_string_lossy().as_ref()),
        )
    }
}

#[pymethods]
impl PyBufReadStream {
    #[pyo3(signature = (size=None))]
    fn read<'a>(&mut self, py: Python<'a>, size: Option<usize>) -> PyResult<Bound<'a, PyBytes>> {
        if let Some(size) = size {
            let mut buf = vec![0; size];
            let ret = py
                .allow_threads(|| self.f.read(&mut buf))
                .map_err(|e| self.map_io_err_to_py_err(e))?;
            Ok(PyBytes::new(py, &buf[..ret]))
        } else {
            let mut buf = Vec::new();
            py.allow_threads(|| self.f.read_to_end(&mut buf))
                .map_err(|e| self.map_io_err_to_py_err(e))?;
            Ok(PyBytes::new(py, &buf))
        }
    }

    fn seekable(&self) -> bool {
        true
    }

    #[pyo3(signature = (offset, whence=None))]
    fn seek(&mut self, py: Python, offset: i64, whence: Option<i8>) -> PyResult<u64> {
        let seekfrom = match whence.unwrap_or(0) {
            0 => std::io::SeekFrom::Start(offset as u64),
            1 => std::io::SeekFrom::Current(offset),
            2 => std::io::SeekFrom::End(offset),
            _ => return Err(PyValueError::new_err("Invalid whence")),
        };

        py.allow_threads(|| self.f.seek(seekfrom))
            .map_err(|e| self.map_io_err_to_py_err(e))
    }

    fn tell(&mut self, py: Python) -> PyResult<u64> {
        py.allow_threads(|| self.f.stream_position())
            .map_err(|e| self.map_io_err_to_py_err(e))
    }

    fn readline<'a>(&mut self, py: Python<'a>) -> PyResult<Bound<'a, PyBytes>> {
        let mut buf = vec![];
        let ret = py
            .allow_threads(|| self.f.read_until(b'\n', &mut buf))
            .map_err(|e| self.map_io_err_to_py_err(e))?;
        buf.truncate(ret);
        Ok(PyBytes::new(py, &buf))
    }

    fn __iter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __next__<'a>(&mut self, py: Python<'a>) -> PyResult<Option<Bound<'a, PyBytes>>> {
        let mut buf = vec![];
        let ret = py
            .allow_threads(|| self.f.read_until(b'\n', &mut buf))
            .map_err(|e| self.map_io_err_to_py_err(e))?;
        if ret == 0 {
            return Ok(None);
        }
        buf.truncate(ret);
        Ok(Some(PyBytes::new(py, &buf)))
    }

    fn close(&mut self) -> PyResult<()> {
        Ok(())
    }

    fn __enter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __exit__(
        &self,
        _exc_type: Option<&Bound<PyType>>,
        _exc_val: Option<&Bound<PyAny>>,
        _exc_tb: Option<&Bound<PyAny>>,
    ) -> PyResult<bool> {
        Ok(false)
    }

    fn readlines<'a>(&mut self, py: Python<'a>) -> PyResult<Bound<'a, PyList>> {
        let ret = PyList::empty(py);
        while let Some(line) = self.__next__(py)? {
            ret.append(line)?;
        }
        Ok(ret)
    }
}

impl Transport {
    fn map_to_py_err(slf: PyRef<Self>, py: Python, e: Error, p: Option<&str>) -> PyErr {
        let obj = slf.into_pyobject(py).unwrap();
        map_transport_err_to_py_err(e, Some(obj.into()), p)
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

    fn get_bytes<'a>(
        slf: Bound<'a, Self>,
        py: Python<'a>,
        path: &'a str,
    ) -> PyResult<Bound<'a, PyBytes>> {
        let t = &slf.borrow().0;
        let ret = py
            .allow_threads(|| t.get_bytes(path))
            .map_err(|e| match e {
                Error::IsADirectoryError(_) => {
                    ReadError::new_err((path.to_string(), "Is a directory".to_string()))
                }
                Error::NotADirectoryError(_) => {
                    NoSuchFile::new_err((path.to_string(), "Not a directory".to_string()))
                }
                e => {
                    let obj = slf.unbind().into_any();
                    map_transport_err_to_py_err(e, Some(obj), Some(path))
                }
            })?;

        Ok(PyBytes::new(py, &ret))
    }

    #[getter]
    fn base(&self) -> PyResult<String> {
        Ok(self.0.base().to_string())
    }

    fn has(&self, py: Python, path: &str) -> PyResult<bool> {
        py.allow_threads(|| self.0.has(path))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    fn has_any(&self, py: Python, paths: Vec<String>) -> PyResult<bool> {
        let paths = paths.iter().map(|p| p.as_str()).collect::<Vec<_>>();
        py.allow_threads(|| self.0.has_any(paths.as_slice()))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    #[pyo3(signature = (path, mode=None))]
    fn mkdir(slf: &Bound<Self>, py: Python, path: &str, mode: Option<PyObject>) -> PyResult<()> {
        let mode = mode.map(perms_from_py_object);
        let t = &slf.borrow().0;
        py.allow_threads(|| t.mkdir(path, mode)).map_err(|e| {
            let obj = slf.to_object(py);
            map_transport_err_to_py_err(e, Some(obj), Some(path))
        })?;
        Ok(())
    }

    #[pyo3(signature = (mode=None))]
    fn ensure_base(&self, py: Python, mode: Option<PyObject>) -> PyResult<bool> {
        let mode = mode.map(perms_from_py_object);
        py.allow_threads(|| self.0.ensure_base(mode))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn local_abspath(&self, py: Python, path: &str) -> PyResult<String> {
        let path = py
            .allow_threads(|| self.0.local_abspath(path))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))?;

        path.to_str()
            .map(|s| s.to_string())
            .ok_or_else(|| PyValueError::new_err(format!("Invalid path: {}", path.display())))
    }

    fn get<'a>(
        slf: PyRef<'a, Self>,
        py: Python<'a>,
        path: &'a str,
    ) -> PyResult<Bound<'a, PyBufReadStream>> {
        let t = &slf.0;
        let ret = py.allow_threads(|| t.get(path)).map_err(|e| match e {
            Error::IsADirectoryError(_) => {
                ReadError::new_err((path.to_string(), "Is a directory".to_string()))
            }
            Error::NotADirectoryError(_) => {
                NoSuchFile::new_err((path.to_string(), "Not a directory".to_string()))
            }
            e => {
                let obj = slf.into_pyobject(py).unwrap().unbind().into_any();
                map_transport_err_to_py_err(e, Some(obj), Some(path))
            }
        })?;
        Bound::new(py, PyBufReadStream::new(ret, Path::new(path)))
    }

    fn get_smart_medium(slf: &Bound<Self>, py: Python) -> PyResult<PyObject> {
        slf.borrow()
            .0
            .get_smart_medium()
            .map_err(|e| Transport::map_to_py_err(slf.borrow(), py, e, None))?;
        // TODO(jelmer)
        Ok(py.None())
    }

    fn stat<'a>(&self, py: Python<'a>, path: &str) -> PyResult<Bound<'a, PyStat>> {
        let t = &self.0;
        let stat = py
            .allow_threads(|| t.stat(path))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))?;
        Bound::new(
            py,
            PyStat {
                st_size: stat.size,
                st_mode: stat.mode,
                st_mtime: stat.mtime,
            },
        )
    }

    #[pyo3(signature = (path=None))]
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

    #[pyo3(signature = (path, data, mode=None))]
    fn put_bytes(
        slf: &Bound<Self>,
        py: Python,
        path: &str,
        data: &[u8],
        mode: Option<PyObject>,
    ) -> PyResult<()> {
        let mode = mode.map(perms_from_py_object).unwrap_or_else(default_perms);
        let t = &slf.borrow().0;
        py.allow_threads(|| t.put_bytes(path, data, Some(mode)))
            .map_err(|e| {
                let obj = slf.to_object(py);
                map_transport_err_to_py_err(e, Some(obj), Some(path))
            })?;
        Ok(())
    }

    #[pyo3(signature = (path, data, mode=None, create_parent_dir=None, dir_mode=None))]
    fn put_bytes_non_atomic(
        slf: &Bound<Self>,
        py: Python,
        path: &str,
        data: &[u8],
        mode: Option<PyObject>,
        create_parent_dir: Option<bool>,
        dir_mode: Option<PyObject>,
    ) -> PyResult<()> {
        let t = &slf.borrow().0;

        py.allow_threads(|| {
            t.put_bytes_non_atomic(
                path,
                data,
                Some(mode.map(perms_from_py_object).unwrap_or_else(default_perms)),
                create_parent_dir,
                dir_mode.map(perms_from_py_object),
            )
        })
        .map_err(|e| {
            let obj = slf.to_object(py);
            map_transport_err_to_py_err(e, Some(obj.into_py(py)), Some(path))
        })?;
        Ok(())
    }

    #[pyo3(signature = (path, file, mode=None))]
    fn put_file(
        slf: &Bound<Self>,
        py: Python,
        path: &str,
        file: PyObject,
        mode: Option<PyObject>,
    ) -> PyResult<u64> {
        let t = &slf.borrow().0;
        let mut file = PyBinaryFile::from(file);
        let ret = py
            .allow_threads(|| {
                t.put_file(
                    path,
                    &mut file,
                    Some(mode.map(perms_from_py_object).unwrap_or_else(default_perms)),
                )
            })
            .map_err(|e| {
                let obj = slf.to_object(py);
                map_transport_err_to_py_err(e, Some(obj), Some(path))
            })?;
        Ok(ret)
    }

    #[pyo3(signature = (path, file, mode=None, create_parent_dir=None, dir_mode=None))]
    fn put_file_non_atomic(
        slf: &Bound<Self>,
        py: Python,
        path: &str,
        file: PyObject,
        mode: Option<PyObject>,
        create_parent_dir: Option<bool>,
        dir_mode: Option<PyObject>,
    ) -> PyResult<()> {
        let t = &slf.borrow().0;
        let mut file = PyBinaryFile::from(file);
        py.allow_threads(|| {
            t.put_file_non_atomic(
                path,
                &mut file,
                Some(mode.map(perms_from_py_object).unwrap_or_else(default_perms)),
                create_parent_dir,
                dir_mode.map(perms_from_py_object),
            )
        })
        .map_err(|e| {
            let obj = slf.to_object(py);
            map_transport_err_to_py_err(e, Some(obj.into_py(py)), Some(path))
        })?;
        Ok(())
    }

    fn delete(&self, py: Python, path: &str) -> PyResult<()> {
        let t = &self.0;
        py.allow_threads(|| t.delete(path))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))?;
        Ok(())
    }

    fn rmdir(&self, py: Python, path: &str) -> PyResult<()> {
        let t = &self.0;

        py.allow_threads(|| t.rmdir(path))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))?;
        Ok(())
    }

    fn rename(&self, py: Python, from: &str, to: &str) -> PyResult<()> {
        let t = &self.0;

        py.allow_threads(|| t.rename(from, to))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))?;
        Ok(())
    }

    #[pyo3(signature = (name, value=None))]
    fn set_segment_parameter(
        &mut self,
        py: Python,
        name: &str,
        value: Option<&str>,
    ) -> PyResult<()> {
        py.allow_threads(|| self.0.set_segment_parameter(name, value))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))?;
        Ok(())
    }

    fn get_segment_parameters(&self, py: Python) -> PyResult<HashMap<String, String>> {
        let t = &self.0;

        py.allow_threads(|| t.get_segment_parameters())
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    #[pyo3(signature = (mode=None))]
    fn create_prefix(&self, py: Python, mode: Option<PyObject>) -> PyResult<()> {
        let t = &self.0;

        py.allow_threads(|| t.create_prefix(mode.map(perms_from_py_object)))
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
    }

    fn lock_write(&self, py: Python, path: &str) -> PyResult<Lock> {
        let t = &self.0;

        py.allow_threads(|| t.lock_write(path))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
            .map(Lock::from)
    }

    fn lock_read(&self, py: Python, path: &str) -> PyResult<Lock> {
        let t = &self.0;

        py.allow_threads(|| t.lock_read(path))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
            .map(Lock::from)
    }

    fn recommended_page_size(&self, py: Python) -> usize {
        py.allow_threads(|| self.0.recommended_page_size())
    }

    fn is_readonly(&self, py: Python) -> bool {
        py.allow_threads(|| self.0.is_readonly())
    }

    #[pyo3(signature = (path, offsets, max_readv_combine=None, bytes_to_read_before_seek=None))]
    fn _readv<'a>(
        slf: &Bound<'a, Self>,
        py: Python<'a>,
        path: &str,
        offsets: Vec<(usize, usize)>,
        max_readv_combine: Option<usize>,
        bytes_to_read_before_seek: Option<usize>,
    ) -> PyResult<Bound<'a, PyAny>> {
        if offsets.is_empty() {
            return Ok(PyList::empty(py).into_any());
        }
        let t = &slf.borrow().0;
        let ret = py.allow_threads(|| t.get(path)).map_err(|e| match e {
            Error::IsADirectoryError(_) => {
                ReadError::new_err((path.to_string(), "Is a directory".to_string()))
            }
            Error::NotADirectoryError(_) => {
                ReadError::new_err((path.to_string(), "Not a directory".to_string()))
            }
            e => {
                let obj = slf.to_object(py);
                map_transport_err_to_py_err(e, Some(obj), Some(path))
            }
        })?;
        let f = Bound::new(py, PyBufReadStream::new(ret, Path::new(path)))?;
        let buffered = seek_and_read(
            py,
            f.into_any(),
            offsets,
            max_readv_combine,
            bytes_to_read_before_seek,
            Some(path),
        )?;
        let list = PyList::new(py, &buffered)?;
        Ok(PyIterator::from_object(&list.into_any())?.into_any())
    }

    #[pyo3(signature = (path, offsets, adjust_for_latency=None, upper_limit=None))]
    fn readv<'a>(
        &self,
        py: Python<'a>,
        path: &str,
        offsets: Vec<(u64, usize)>,
        adjust_for_latency: Option<bool>,
        upper_limit: Option<u64>,
    ) -> PyResult<Bound<'a, PyIterator>> {
        let t = &self.0;
        let buffered = py
            .allow_threads(|| {
                t.readv(
                    path,
                    offsets,
                    adjust_for_latency.unwrap_or(false),
                    upper_limit,
                )
            })
            .map(|r| {
                r.map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
                    .map(|(o, r)| (o, PyBytes::new(py, &r)))
            })
            .collect::<PyResult<Vec<(u64, Bound<PyBytes>)>>>()?;
        let list = PyList::new(py, &buffered)?;
        PyIterator::from_object(&list)
    }

    fn listable(&self, py: Python) -> bool {
        py.allow_threads(|| self.0.listable())
    }

    fn list_dir(&self, py: Python, path: &str) -> PyResult<Vec<String>> {
        py.allow_threads(|| {
            self.0
                .list_dir(path)
                .map(|r| r.map_err(|e| map_transport_err_to_py_err(e, None, Some(path))))
                .collect::<PyResult<Vec<_>>>()
        })
    }

    #[pyo3(signature = (path, bytes, mode=None))]
    fn append_bytes(
        &self,
        py: Python,
        path: &str,
        bytes: &[u8],
        mode: Option<PyObject>,
    ) -> PyResult<u64> {
        let mode = mode.map(perms_from_py_object);
        py.allow_threads(|| self.0.append_bytes(path, bytes, mode))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    #[pyo3(signature = (path, file, mode=None))]
    fn append_file(
        &self,
        py: Python,
        path: &str,
        file: PyObject,
        mode: Option<PyObject>,
    ) -> PyResult<u64> {
        let mut file = PyBinaryFile::from(file);
        let mode = mode.map(perms_from_py_object);
        py.allow_threads(|| self.0.append_file(path, &mut file, mode))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    fn iter_files_recursive<'a>(&self, py: Python<'a>) -> PyResult<Bound<'a, PyList>> {
        self.0
            .iter_files_recursive()
            .map(|r| {
                r.map_err(|e| map_transport_err_to_py_err(e, None, Some(".")))
                    .map(|o| o.to_string())
            })
            .collect::<PyResult<Vec<_>>>()
            .and_then(move |v| PyList::new(py, &v))
    }

    #[pyo3(signature = (path, mode=None))]
    fn open_write_stream(
        slf: &Bound<Self>,
        py: Python,
        path: &str,
        mode: Option<PyObject>,
    ) -> PyResult<PyWriteStream> {
        let t = &slf.borrow().0;
        py.allow_threads(|| t.open_write_stream(path, mode.map(perms_from_py_object)))
            .map_err(|e| Transport::map_to_py_err(slf.borrow(), py, e, Some(path)))
            .map(PyWriteStream)
    }

    fn delete_tree(&self, py: Python, path: &str) -> PyResult<()> {
        py.allow_threads(|| self.0.delete_tree(path))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    fn r#move(&self, py: Python, from: &str, to: &str) -> PyResult<()> {
        py.allow_threads(|| self.0.r#move(from, to))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))
    }

    fn copy_tree(&self, py: Python, from: &str, to: &str) -> PyResult<()> {
        py.allow_threads(|| self.0.copy_tree(from, to))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))
    }

    fn copy_tree_to_transport(&self, py: Python, to_transport: PyObject) -> PyResult<()> {
        if let Ok(t) = to_transport.clone_ref(py).extract::<PyRef<Transport>>(py) {
            let t = t.0.as_ref();
            py.allow_threads(|| self.0.copy_tree_to_transport(t))
                .map_err(|e| map_transport_err_to_py_err(e, None, Some(".")))
        } else {
            let t = Box::new(breezy_transport::pyo3::PyTransport::from(to_transport));
            py.allow_threads(|| self.0.copy_tree_to_transport(t.as_ref()))
                .map_err(|e| map_transport_err_to_py_err(e, None, Some(".")))
        }
    }

    fn hardlink(&self, py: Python, from: &str, to: &str) -> PyResult<()> {
        py.allow_threads(|| self.0.hardlink(from, to))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))
    }

    fn symlink(&self, py: Python, from: &str, to: &str) -> PyResult<()> {
        py.allow_threads(|| self.0.symlink(from, to))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(from)))
    }

    fn readlink(&self, py: Python, path: &str) -> PyResult<String> {
        py.allow_threads(|| self.0.readlink(path))
            .map_err(|e| map_transport_err_to_py_err(e, None, Some(path)))
    }

    #[pyo3(signature = (relpaths, to_transport, mode=None))]
    fn copy_to(
        &self,
        py: Python,
        relpaths: PyObject,
        to_transport: PyObject,
        mode: Option<PyObject>,
    ) -> PyResult<usize> {
        let relpaths = relpaths
            .bind(py)
            .try_iter()?
            .map(|o| o?.extract::<String>())
            .collect::<PyResult<Vec<_>>>()?;

        let relpaths_ref = relpaths.iter().map(|s| s.as_str()).collect::<Vec<_>>();

        if let Ok(t) = to_transport.clone_ref(py).downcast_bound::<Transport>(py) {
            let t = &t.borrow().0;
            py.allow_threads(|| {
                self.0.copy_to(
                    relpaths_ref.as_slice(),
                    t.as_ref(),
                    mode.map(perms_from_py_object),
                )
            })
            .map_err(|e| map_transport_err_to_py_err(e, None, None))
        } else {
            let t = Box::new(breezy_transport::pyo3::PyTransport::from(to_transport));
            py.allow_threads(|| {
                self.0
                    .copy_to(
                        relpaths_ref.as_slice(),
                        t.as_ref(),
                        mode.map(perms_from_py_object),
                    )
                    .map_err(|e| map_transport_err_to_py_err(e, None, None))
            })
        }
    }

    fn _can_roundtrip_unix_modebits(&self) -> bool {
        self.0.can_roundtrip_unix_modebits()
    }

    fn copy(&self, py: Python, from: &str, to: &str) -> PyResult<()> {
        py.allow_threads(|| self.0.copy(from, to))
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
        self.0.unlock().map_err(map_lock_err_to_py_err)
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

    #[pyo3(signature = (offset=None))]
    fn clone<'a>(
        slf: PyRef<'a, Self>,
        py: Python<'a>,
        offset: Option<PyObject>,
    ) -> PyResult<Bound<'a, LocalTransport>> {
        let super_ = slf.as_ref();
        let inner = if let Some(offset) = offset {
            let offset = offset.extract::<String>(py)?;
            super_.0.clone(Some(&offset))
        } else {
            super_.0.clone(None)
        }
        .map_err(|e| map_transport_err_to_py_err(e, None, None))?;

        let init = PyClassInitializer::from(Transport(inner));
        let init = init.add_subclass(Self {});
        Bound::new(py, init)
    }
}

#[pyfunction]
fn get_test_permutations(py: Python) -> PyResult<Bound<PyList>> {
    let test_server_module = py.import("breezy.tests.test_server")?;
    let local_url_server = test_server_module.getattr("LocalURLServer")?;
    let local_transport = py
        .import("breezy.transport.local")?
        .getattr("LocalTransport")?;
    let ret = PyList::empty(py);
    ret.append((local_transport, local_url_server))?;
    Ok(ret)
}

#[pyfunction]
#[pyo3(signature = (offsets, limit=None, fudge_factor=None, max_size=None))]
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
#[pyo3(signature = (file, offsets, max_readv_combine=None, bytes_to_read_before_seek=None, path=None))]
fn seek_and_read(
    py: Python,
    file: Bound<PyAny>,
    offsets: Vec<(usize, usize)>,
    max_readv_combine: Option<usize>,
    bytes_to_read_before_seek: Option<usize>,
    path: Option<&str>,
) -> PyResult<Vec<(usize, PyObject)>> {
    let f = PyBinaryFile::from(file);
    let mut data = py
        .allow_threads(|| {
            breezy_transport::readv::seek_and_read(
                f,
                offsets,
                max_readv_combine.unwrap_or(DEFAULT_MAX_READV_COMBINE),
                bytes_to_read_before_seek.unwrap_or(DEFAULT_BYTES_TO_READ_BEFORE_SEEK),
            )
        })
        .map_err(|e| -> PyErr { e.into() })?;

    std::iter::from_fn(move || py.allow_threads(|| data.next()))
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

#[pyfunction]
#[pyo3(signature = (offsets, upper_limit=None, recommended_page_size=None))]
fn sort_expand_and_combine(
    offsets: Vec<(u64, usize)>,
    upper_limit: Option<u64>,
    recommended_page_size: Option<usize>,
) -> Vec<(u64, usize)> {
    breezy_transport::readv::sort_expand_and_combine(
        offsets,
        upper_limit,
        recommended_page_size.unwrap_or(4 * 1024),
    )
}

#[pyclass]
struct PyFile(BufReader<Box<std::fs::File>>);

impl PyFile {
    fn new(f: Box<std::fs::File>, _path: &Path) -> Self {
        Self(BufReader::new(f))
    }
}

#[pymethods]
impl PyFile {
    fn seekable(&self) -> bool {
        true
    }

    #[pyo3(signature = (size=None))]
    fn read<'a>(&mut self, py: Python<'a>, size: Option<usize>) -> PyResult<Bound<'a, PyBytes>> {
        if let Some(size) = size {
            let mut buf = vec![0; size];
            let ret = py
                .allow_threads(|| self.0.read(&mut buf))
                .map_err(|e| -> PyErr { e.into() })?;
            Ok(PyBytes::new(py, &buf[..ret]))
        } else {
            let mut buf = Vec::new();
            py.allow_threads(|| self.0.read_to_end(&mut buf))
                .map_err(|e| -> PyErr { e.into() })?;
            Ok(PyBytes::new(py, &buf))
        }
    }

    fn write(&mut self, py: Python, data: &[u8]) -> PyResult<usize> {
        py.allow_threads(|| self.0.get_mut().write(data))
            .map_err(|e| e.into())
    }

    fn readline<'a>(&mut self, py: Python<'a>) -> PyResult<Bound<'a, PyBytes>> {
        let mut buf = vec![];
        let ret = py.allow_threads(|| self.0.read_until(b'\n', &mut buf))?;
        buf.truncate(ret);
        Ok(PyBytes::new(py, &buf))
    }

    fn __iter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __next__<'a>(&mut self, py: Python<'a>) -> PyResult<Option<Bound<'a, PyBytes>>> {
        let mut buf = vec![];
        let ret = py
            .allow_threads(|| self.0.read_until(b'\n', &mut buf))
            .map_err(|e| -> PyErr { e.into() })?;
        if ret == 0 {
            return Ok(None);
        }
        buf.truncate(ret);
        Ok(Some(PyBytes::new(py, &buf)))
    }

    fn readlines<'a>(&mut self, py: Python<'a>) -> PyResult<Bound<'a, PyList>> {
        let ret = PyList::empty(py);
        while let Some(line) = self.__next__(py)? {
            ret.append(line)?;
        }
        Ok(ret)
    }

    #[pyo3(signature = (offset, whence=None))]
    fn seek(&mut self, offset: i64, whence: Option<i8>) -> PyResult<u64> {
        let seekfrom = match whence.unwrap_or(0) {
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

    fn __enter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __exit__(
        &self,
        _exc_type: Option<&Bound<PyType>>,
        _exc_val: Option<&Bound<PyAny>>,
        _exc_tb: Option<&Bound<PyAny>>,
    ) -> PyResult<bool> {
        Ok(false)
    }

    fn flush(&mut self) -> PyResult<()> {
        self.0.get_mut().flush().map_err(|e| e.into())
    }

    fn writelines(&mut self, py: Python, lines: &Bound<PyList>) -> PyResult<()> {
        for line in lines.iter() {
            self.write(py, line.extract::<&[u8]>()?)?;
        }
        Ok(())
    }

    #[pyo3(signature = (size=None))]
    fn truncate(&mut self, py: Python, size: Option<u64>) -> PyResult<()> {
        let size = size.map_or_else(|| py.allow_threads(|| self.tell()), Ok)?;
        py.allow_threads(|| self.0.get_mut().set_len(size))
            .map_err(|e| e.into())
    }

    #[cfg(unix)]
    fn fileno(&self, py: Python) -> PyResult<i32> {
        use std::os::unix::io::AsRawFd;
        Ok(py.allow_threads(|| self.0.get_ref().as_raw_fd()))
    }
}

fn map_lock_err_to_py_err(err: LockError) -> PyErr {
    match err {
        LockError::Contention(p) => LockContention::new_err((p,)),
        LockError::Failed(p, w) => LockFailed::new_err((p, w)),
        LockError::IoError(e) => e.into(),
    }
}

#[pyclass]
struct ReadLock(Option<breezy_transport::filelock::ReadLock>);

#[pyclass]
struct WriteLock(breezy_transport::filelock::WriteLock);

#[pymethods]
impl ReadLock {
    fn unlock(&mut self) -> PyResult<()> {
        if let Some(mut read_lock) = self.0.take() {
            read_lock.unlock().map_err(map_lock_err_to_py_err)
        } else {
            debug!("ReadLock already unlocked");
            Ok(())
        }
    }

    #[new]
    #[pyo3(signature = (filename, strict_locks=None))]
    fn new(filename: PathBuf, strict_locks: Option<bool>) -> PyResult<Self> {
        Ok(Self(Some(
            breezy_transport::filelock::ReadLock::new(&filename, strict_locks.unwrap_or(false))
                .map_err(map_lock_err_to_py_err)?,
        )))
    }

    fn temporary_write_lock<'a>(
        slf: Bound<'a, Self>,
        py: Python<'a>,
    ) -> PyResult<(bool, Bound<'a, PyAny>)> {
        let mut m = slf.borrow_mut();
        if let Some(read_lock) = m.0.take() {
            match read_lock.temporary_write_lock() {
                Ok(twl) => Ok((
                    true,
                    Bound::new(py, TemporaryWriteLock(Some(twl)))?.into_any(),
                )),
                Err((rl, LockError::Contention(_))) => {
                    m.0 = Some(rl);
                    Ok((false, slf.into_any()))
                }
                Err((_rl, LockError::Failed(p, w))) => Err(LockFailed::new_err((p, w))),
                Err((_rl, LockError::IoError(e))) => Err(e.into()),
            }
        } else {
            Err(PyRuntimeError::new_err("ReadLock already unlocked"))
        }
    }

    #[getter]
    fn f(&self) -> PyResult<PyFile> {
        if let Some(read_lock) = &self.0 {
            Ok(PyFile::new(read_lock.file()?, read_lock.path()))
        } else {
            Err(PyRuntimeError::new_err("ReadLock already unlocked"))
        }
    }
}

#[pyclass]
struct TemporaryWriteLock(Option<breezy_transport::filelock::TemporaryWriteLock>);

#[pymethods]
impl TemporaryWriteLock {
    fn restore_read_lock(&mut self) -> PyResult<ReadLock> {
        if let Some(lock) = self.0.take() {
            let rl = lock.restore_read_lock();
            Ok(ReadLock(Some(rl)))
        } else {
            Err(PyRuntimeError::new_err(
                "TemporaryWriteLock already unlocked",
            ))
        }
    }

    #[getter]
    fn f(&self) -> PyResult<PyFile> {
        if let Some(lock) = &self.0 {
            Ok(PyFile::new(lock.file()?, lock.path()))
        } else {
            Err(PyRuntimeError::new_err(
                "TemporaryWriteLock already unlocked",
            ))
        }
    }
}

#[pymethods]
impl WriteLock {
    fn unlock(&mut self) -> PyResult<()> {
        self.0.unlock().map_err(map_lock_err_to_py_err)
    }

    #[new]
    #[pyo3(signature = (filename, strict_locks=None))]
    fn new(filename: PathBuf, strict_locks: Option<bool>) -> PyResult<Self> {
        Ok(Self(
            breezy_transport::filelock::WriteLock::new(&filename, strict_locks.unwrap_or(false))
                .map_err(map_lock_err_to_py_err)?,
        ))
    }

    #[getter]
    fn f(&self) -> PyResult<PyFile> {
        Ok(PyFile::new(self.0.file()?, self.0.path()))
    }
}

mod sftp;

#[pymodule]
fn _transport_rs(py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    m.add_class::<Transport>()?;
    let localm = PyModule::new(py, "local")?;
    localm.add_class::<LocalTransport>()?;
    m.add_submodule(&localm)?;
    m.add_class::<ReadLock>()?;
    m.add_class::<WriteLock>()?;
    m.add_class::<TemporaryWriteLock>()?;
    m.add_function(wrap_pyfunction!(get_test_permutations, m)?)?;
    m.add_wrapped(wrap_pyfunction!(seek_and_read))?;
    m.add_wrapped(wrap_pyfunction!(coalesce_offsets))?;
    m.add_wrapped(wrap_pyfunction!(sort_expand_and_combine))?;

    let sftpm = PyModule::new(py, "sftp")?;
    sftp::_sftp_rs(py, &sftpm)?;
    m.add_submodule(&sftpm)?;
    m.add_class::<ReadLock>()?;
    m.add_class::<WriteLock>()?;
    m.add_class::<TemporaryWriteLock>()?;

    Ok(())
}
