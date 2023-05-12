use breezy_transport::lock::Lock as LockTrait;
use breezy_transport::lock::{FileLock, LockError};
use log::debug;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyList, PyType};
use pyo3_file::PyFileLikeObject;
use std::io::{BufRead, BufReader, Read, Seek, Write};
use std::path::{Path, PathBuf};

import_exception!(breezy.errors, ShortReadvError);
import_exception!(breezy.errors, LockContention);
import_exception!(breezy.errors, LockFailed);

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
        .collect::<Result<Vec<_>, _>>()
}

#[pyfunction]
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
struct PyFile(BufReader<Box<std::fs::File>>, PathBuf);

impl PyFile {
    fn new(f: Box<std::fs::File>, path: &Path) -> Self {
        Self(BufReader::new(f), path.to_path_buf())
    }
}

#[pymethods]
impl PyFile {
    fn seekable(&self) -> bool {
        true
    }

    fn read(&mut self, py: Python, size: Option<usize>) -> PyResult<PyObject> {
        if let Some(size) = size {
            let mut buf = vec![0; size];
            let ret = py
                .allow_threads(|| self.0.read(&mut buf))
                .map_err(|e| -> PyErr { e.into() })?;
            Ok(PyBytes::new(py, &buf[..ret]).to_object(py))
        } else {
            let mut buf = Vec::new();
            py.allow_threads(|| self.0.read_to_end(&mut buf))
                .map_err(|e| -> PyErr { e.into() })?;
            Ok(PyBytes::new(py, &buf).to_object(py))
        }
    }

    fn write(&mut self, py: Python, data: &[u8]) -> PyResult<usize> {
        py.allow_threads(|| self.0.get_mut().write(data))
            .map_err(|e| e.into())
    }

    fn readline(&mut self, py: Python) -> PyResult<PyObject> {
        let mut buf = vec![];
        let ret = py.allow_threads(|| self.0.read_until(b'\n', &mut buf))?;
        buf.truncate(ret);
        Ok(PyBytes::new(py, &buf).to_object(py).to_object(py))
    }

    fn __iter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __next__(&mut self, py: Python) -> PyResult<Option<PyObject>> {
        let mut buf = vec![];
        let ret = py
            .allow_threads(|| self.0.read_until(b'\n', &mut buf))
            .map_err(|e| -> PyErr { e.into() })?;
        if ret == 0 {
            return Ok(None);
        }
        buf.truncate(ret);
        Ok(Some(PyBytes::new(py, &buf).to_object(py).to_object(py)))
    }

    fn readlines(&mut self, py: Python) -> PyResult<PyObject> {
        let ret = PyList::empty(py);
        while let Some(line) = self.__next__(py)? {
            ret.append(line)?;
        }
        Ok(ret.to_object(py))
    }

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
        _exc_type: Option<&PyType>,
        _exc_val: Option<&PyAny>,
        _exc_tb: Option<&PyAny>,
    ) -> PyResult<bool> {
        Ok(false)
    }

    fn flush(&mut self) -> PyResult<()> {
        self.0.get_mut().flush().map_err(|e| e.into())
    }

    fn writelines(&mut self, py: Python, lines: &PyList) -> PyResult<()> {
        for line in lines.iter() {
            self.write(py, line.extract::<&[u8]>().unwrap())?;
        }
        Ok(())
    }

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
    fn new(filename: PathBuf, strict_locks: Option<bool>) -> PyResult<Self> {
        Ok(Self(Some(
            breezy_transport::filelock::ReadLock::new(&filename, strict_locks.unwrap_or(false))
                .map_err(map_lock_err_to_py_err)?,
        )))
    }

    fn temporary_write_lock(slf: &PyCell<Self>, py: Python) -> PyResult<(bool, PyObject)> {
        let mut m = slf.borrow_mut();
        if let Some(read_lock) = m.0.take() {
            match read_lock.temporary_write_lock() {
                Ok(twl) => Ok((true, TemporaryWriteLock(Some(twl)).into_py(py))),
                Err((rl, LockError::Contention(_))) => {
                    m.0 = Some(rl);
                    Ok((false, slf.to_object(slf.py())))
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
fn _transport_rs(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(seek_and_read))?;
    m.add_wrapped(wrap_pyfunction!(coalesce_offsets))?;
    m.add_wrapped(wrap_pyfunction!(sort_expand_and_combine))?;

    let sftpm = PyModule::new(py, "sftp")?;
    sftp::_sftp_rs(py, sftpm)?;
    m.add_submodule(sftpm)?;
    m.add_class::<ReadLock>()?;
    m.add_class::<WriteLock>()?;
    m.add_class::<TemporaryWriteLock>()?;

    Ok(())
}
