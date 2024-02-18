#![allow(non_snake_case)]
use breezy_osutils::Kind;
use pyo3::create_exception;
use pyo3::exceptions::{PyIOError, PyTypeError, PyValueError};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyIterator, PyList, PyTuple};
use pyo3::wrap_pyfunction;
use pyo3::PyErr;
use pyo3_filelike::PyBinaryFile;
use std::collections::HashSet;
use std::ffi::OsString;
use std::fs::Permissions;
use std::io::{BufRead, Read};
use std::iter::Iterator;
use std::os::unix::ffi::OsStringExt;
use std::path::{Path, PathBuf};
use termion::color::Color;

create_exception!(
    breezy_osutils,
    UnsupportedTimezoneFormat,
    pyo3::exceptions::PyException
);

import_exception!(breezy.errors, IllegalPath);
import_exception!(breezy.errors, PathNotChild);
import_exception!(breezy.errors, DirectoryNotEmpty);
import_exception!(breezy.errors, BinaryFile);

#[pyclass]
struct PyChunksToLinesIterator {
    chunk_iter: PyObject,
    tail: Option<Vec<u8>>,
}

#[pymethods]
impl PyChunksToLinesIterator {
    #[new]
    fn new(chunk_iter: PyObject) -> PyResult<Self> {
        Ok(PyChunksToLinesIterator {
            chunk_iter,
            tail: None,
        })
    }

    fn __iter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __next__(&mut self) -> PyResult<Option<Py<PyAny>>> {
        Python::with_gil(move |py| loop {
            if let Some(mut chunk) = self.tail.take() {
                if let Some(newline) = memchr::memchr(b'\n', &chunk) {
                    if newline == chunk.len() - 1 {
                        assert!(!chunk.is_empty());
                        return Ok(Some(PyBytes::new(py, chunk.as_slice()).to_object(py)));
                    } else {
                        assert!(!chunk.is_empty());
                        self.tail = Some(chunk[newline + 1..].to_vec());
                        let bytes = PyBytes::new(py, &chunk[..=newline]);
                        return Ok(Some(bytes.to_object(py)));
                    }
                } else {
                    if let Some(next_chunk) = self.chunk_iter.downcast::<PyIterator>(py)?.next() {
                        let next_chunk = next_chunk?;
                        let next_chunk = next_chunk.extract::<&[u8]>()?;
                        chunk.extend_from_slice(next_chunk);
                    } else {
                        assert!(!chunk.is_empty());
                        return Ok(Some(PyBytes::new(py, &chunk).to_object(py)));
                    }
                    if !chunk.is_empty() {
                        self.tail = Some(chunk);
                    }
                }
            } else if let Some(next_chunk) = self.chunk_iter.downcast::<PyIterator>(py)?.next() {
                let next_chunk_py = next_chunk?;
                let next_chunk = next_chunk_py.extract::<&[u8]>()?;
                if let Some(newline) = memchr::memchr(b'\n', next_chunk) {
                    if newline == next_chunk.len() - 1 {
                        let line = next_chunk_py.downcast::<PyBytes>()?;
                        return Ok(Some(line.to_object(py)));
                    }
                }

                if !next_chunk.is_empty() {
                    self.tail = Some(next_chunk.to_vec());
                }
            } else {
                return Ok(None);
            }
        })
    }
}

fn extract_path(object: &PyAny) -> PyResult<PathBuf> {
    if let Ok(path) = object.extract::<Vec<u8>>() {
        Ok(PathBuf::from(OsString::from_vec(path)))
    } else if let Ok(path) = object.extract::<PathBuf>() {
        Ok(path)
    } else {
        Err(PyTypeError::new_err("path must be a string or bytes"))
    }
}

#[pyfunction]
fn chunks_to_lines(py: Python, chunks: PyObject) -> PyResult<PyObject> {
    let ret = PyList::empty(py);
    let chunk_iter = chunks.call_method0(py, "__iter__");
    if chunk_iter.is_err() {
        return Err(PyTypeError::new_err("chunks must be iterable"));
    }
    let iter = PyChunksToLinesIterator::new(chunk_iter?)?;
    let iter = iter.into_py(py);
    ret.call_method1("extend", (iter,))?;
    Ok(ret.into_py(py))
}

#[pyfunction]
fn split_lines(py: Python, mut chunks: PyObject) -> PyResult<PyObject> {
    let ret = PyList::empty(py);
    if let Ok(chunk) = chunks.extract::<&PyBytes>(py) {
        chunks = PyList::new(py, [chunk]).into_py(py);
    }

    let chunk_iter = chunks.call_method0(py, "__iter__");
    if chunk_iter.is_err() {
        return Err(PyTypeError::new_err("chunks must be iterable"));
    }
    let iter = PyChunksToLinesIterator::new(chunk_iter?)?;
    let iter = iter.into_py(py);
    ret.call_method1("extend", (iter,))?;
    Ok(ret.into_py(py))
}

#[pyfunction]
fn chunks_to_lines_iter(py: Python, chunk_iter: PyObject) -> PyResult<PyObject> {
    let iter = PyChunksToLinesIterator::new(chunk_iter)?;
    Ok(iter.into_py(py))
}

/// Calculate the SHA1 of a file by reading the full text
#[pyfunction]
fn sha_file_by_name(py: Python, object: &PyAny) -> PyResult<PyObject> {
    let pathbuf = extract_path(object)?;
    let digest = breezy_osutils::sha::sha_file_by_name(pathbuf.as_path()).map_err(PyErr::from)?;
    Ok(PyBytes::new(py, digest.as_bytes()).into_py(py))
}

#[pyfunction]
fn sha_string(py: Python, string: &[u8]) -> PyResult<PyObject> {
    let digest = breezy_osutils::sha::sha_string(string);
    Ok(PyBytes::new(py, digest.as_bytes()).into_py(py))
}

/// Return the sha-1 of concatenation of strings
#[pyfunction]
fn sha_strings(py: Python, strings: &PyAny) -> PyResult<PyObject> {
    let iter = strings.iter()?;
    let digest =
        breezy_osutils::sha::sha_chunks(iter.map(|x| x.unwrap().extract::<&[u8]>().unwrap()));
    Ok(PyBytes::new(py, digest.as_bytes()).into_py(py))
}

/// Calculate the hexdigest of an open file.
///
/// The file cursor should be already at the start.
#[pyfunction]
fn sha_file(py: Python, file: PyObject) -> PyResult<PyObject> {
    let mut file = PyBinaryFile::from(file);
    let digest = breezy_osutils::sha::sha_file(&mut file).map_err(PyErr::from)?;
    Ok(PyBytes::new(py, digest.as_bytes()).into_py(py))
}

/// Calculate the size and hexdigest of an open file.
///
/// The file cursor should be already at the start and
/// the caller is responsible for closing the file afterwards.
#[pyfunction]
fn size_sha_file(py: Python, file: PyObject) -> PyResult<(usize, PyObject)> {
    let mut file = PyBinaryFile::from(file);
    let (size, digest) = breezy_osutils::sha::size_sha_file(&mut file).map_err(PyErr::from)?;
    Ok((size, PyBytes::new(py, digest.as_bytes()).into_py(py)))
}

#[pyfunction]
fn normalized_filename(filename: &PyAny, policy: Option<&str>) -> PyResult<(PathBuf, bool)> {
    if policy.is_none() {
        if breezy_osutils::path::normalizes_filenames() {
            _accessible_normalized_filename(filename)
        } else {
            _inaccessible_normalized_filename(filename)
        }
    } else if policy == Some("accessible") {
        _accessible_normalized_filename(filename)
    } else if policy == Some("inaccessible") {
        _inaccessible_normalized_filename(filename)
    } else {
        Err(PyValueError::new_err(
            "policy must be 'accessible', 'inaccessible' or None",
        ))
    }
}

#[pyfunction]
fn _inaccessible_normalized_filename(filename: &PyAny) -> PyResult<(PathBuf, bool)> {
    let filename = extract_path(filename)?;
    if let Some(filename) =
        breezy_osutils::path::inaccessible_normalized_filename(filename.as_path())
    {
        Ok(filename)
    } else {
        Ok((filename, true))
    }
}

#[pyfunction]
fn _accessible_normalized_filename(filename: &PyAny) -> PyResult<(PathBuf, bool)> {
    let filename = extract_path(filename)?;
    if let Some(filename) = breezy_osutils::path::accessible_normalized_filename(filename.as_path())
    {
        Ok(filename)
    } else {
        Ok((filename, false))
    }
}

#[pyfunction]
fn normalizes_filenames() -> bool {
    breezy_osutils::path::normalizes_filenames()
}

#[pyfunction]
fn is_inside(path: &PyAny, parent: &PyAny) -> PyResult<bool> {
    let path = extract_path(path)?;
    let parent = extract_path(parent)?;
    Ok(breezy_osutils::path::is_inside(
        path.as_path(),
        parent.as_path(),
    ))
}

#[pyfunction]
fn is_inside_any(dir_list: &PyAny, path: &PyAny) -> PyResult<bool> {
    let path = extract_path(path)?;
    let mut c_dir_list: Vec<PathBuf> = Vec::new();
    for dir in dir_list.iter()? {
        c_dir_list.push(extract_path(dir?)?);
    }
    Ok(breezy_osutils::path::is_inside_any(
        &c_dir_list
            .iter()
            .map(|p| p.as_path())
            .collect::<Vec<&Path>>(),
        path.as_path(),
    ))
}

#[pyfunction]
fn is_inside_or_parent_of_any(dir_list: &PyAny, path: &PyAny) -> PyResult<bool> {
    let path = extract_path(path)?;
    let mut c_dir_list: Vec<PathBuf> = Vec::new();
    for dir in dir_list.iter()? {
        c_dir_list.push(extract_path(dir?)?);
    }
    Ok(breezy_osutils::path::is_inside_or_parent_of_any(
        &c_dir_list
            .iter()
            .map(|p| p.as_path())
            .collect::<Vec<&Path>>(),
        path.as_path(),
    ))
}

#[pyfunction]
pub fn minimum_path_selection(paths: &PyAny) -> PyResult<HashSet<String>> {
    let mut path_set: HashSet<PathBuf> = HashSet::new();
    for path in paths.iter()? {
        path_set.insert(extract_path(path?)?);
    }
    let paths = breezy_osutils::path::minimum_path_selection(
        path_set
            .iter()
            .map(|p| p.as_path())
            .collect::<HashSet<&Path>>(),
    );
    Ok(paths
        .iter()
        .map(|x| x.to_string_lossy().to_string())
        .collect())
}

#[pyfunction]
fn set_or_unset_env(key: &str, value: Option<&str>) -> PyResult<Py<PyAny>> {
    // Note that we're not calling out to breezy_osutils::set_or_unset_env here, because it doesn't
    // change the environment in Python.
    Python::with_gil(|py| {
        let os = py.import("os")?;
        let environ = os.getattr("environ")?;
        let old = environ.call_method1("get", (key, py.None()))?;
        if let Some(value) = value {
            environ.set_item(key, value)?;
            std::env::set_var(key, value);
        } else {
            if old.is_none() {
                return Ok(py.None());
            }
            environ.del_item(key)?;
            std::env::remove_var(key);
        }
        Ok(old.into_py(py))
    })
}

#[pyfunction]
fn parent_directories(py: Python, path: &PyAny) -> PyResult<PyObject> {
    let path = extract_path(path)?;
    let parents: Vec<&Path> = breezy_osutils::path::parent_directories(&path).collect();
    Ok(parents.into_py(py))
}

#[pyfunction]
fn available_backup_name(py: Python, path: &PyAny, exists: PyObject) -> PyResult<PathBuf> {
    let path = extract_path(path)?;
    let exists = |p: &Path| -> PyResult<bool> {
        let ret = exists.call1(py, (p,))?;
        ret.extract::<bool>(py)
    };

    breezy_osutils::path::available_backup_name(path.as_path(), &exists)
}

#[pyfunction]
fn find_executable_on_path(executable: &str) -> PyResult<Option<String>> {
    Ok(breezy_osutils::path::find_executable_on_path(executable))
}

#[pyfunction]
fn legal_path(path: &PyAny) -> PyResult<bool> {
    let path = extract_path(path)?;
    Ok(breezy_osutils::path::legal_path(path.as_path()))
}

#[pyfunction]
fn check_legal_path(path: &PyAny) -> PyResult<()> {
    let path = extract_path(path)?;
    if !breezy_osutils::path::legal_path(path.as_path()) {
        Err(IllegalPath::new_err((path,)))
    } else {
        Ok(())
    }
}

#[pyfunction]
fn local_time_offset(t: Option<&PyAny>) -> PyResult<i64> {
    if let Some(t) = t {
        let t = t.extract::<f64>()?;
        Ok(breezy_osutils::time::local_time_offset(Some(t as i64)))
    } else {
        Ok(breezy_osutils::time::local_time_offset(None))
    }
}

#[pyfunction]
fn format_local_date(
    py: Python,
    t: PyObject,
    offset: Option<i32>,
    timezone: Option<&str>,
    date_format: Option<&str>,
    show_offset: Option<bool>,
) -> PyResult<String> {
    let t = if let Ok(t) = t.extract::<f64>(py) {
        t as i64
    } else if let Ok(t) = t.extract::<i64>(py) {
        t
    } else {
        return Err(PyValueError::new_err("t must be a float"));
    };
    let timezone = breezy_osutils::time::Timezone::from(timezone.unwrap_or("original"));
    if timezone.is_none() {
        return Err(UnsupportedTimezoneFormat::new_err("Unsupported timezone"));
    }
    let timezone = timezone.unwrap();
    Ok(breezy_osutils::time::format_local_date(
        t,
        offset,
        timezone,
        date_format,
        show_offset.unwrap_or(true),
    ))
}

#[pyfunction]
fn rand_chars(len: usize) -> PyResult<String> {
    Ok(breezy_osutils::rand_chars(len))
}

#[pyclass]
struct PyIterableFile {
    inner: breezy_osutils::iterablefile::IterableFile<
        Box<dyn Iterator<Item = std::io::Result<Vec<u8>>> + Send>,
    >,
    closed: bool,
}

#[pymethods]
impl PyIterableFile {
    fn __enter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __exit__(
        &mut self,
        _py: Python,
        _exc_type: &PyAny,
        _exc_value: &PyAny,
        _traceback: &PyAny,
    ) -> PyResult<bool> {
        self.check_closed(_py)?;
        Ok(false)
    }

    fn check_closed(&self, _py: Python) -> PyResult<()> {
        if self.closed {
            Err(PyIOError::new_err("I/O operation on closed file"))
        } else {
            Ok(())
        }
    }

    fn read(&mut self, py: Python, size: Option<usize>) -> PyResult<PyObject> {
        self.check_closed(py)?;
        let mut buf = Vec::new();
        let read = if let Some(size) = size {
            let inner = &mut self.inner;
            let mut handle = inner.take(size as u64);
            handle.read_to_end(&mut buf)
        } else {
            self.inner.read_to_end(&mut buf)
        };
        if PyErr::occurred(py) {
            return Err(PyErr::fetch(py));
        }
        buf.truncate(read?);
        Ok(PyBytes::new(py, &buf).to_object(py))
    }

    fn close(&mut self, _py: Python) -> PyResult<()> {
        self.closed = true;
        Ok(())
    }

    fn readlines(&mut self, py: Python) -> PyResult<PyObject> {
        self.check_closed(py)?;
        let lines = PyList::empty(py);
        while let Some(line) = self.readline(py, None)? {
            lines.append(line)?;
        }
        Ok(lines.to_object(py))
    }

    fn __iter__(slf: PyRef<Self>) -> PyRef<Self> {
        slf
    }

    fn __next__(&mut self, py: Python) -> PyResult<Option<PyObject>> {
        self.readline(py, None)
    }

    fn readline(&mut self, py: Python, _size_hint: Option<usize>) -> PyResult<Option<PyObject>> {
        self.check_closed(py)?;
        let mut buf = Vec::new();
        let read = self.inner.read_until(b'\n', &mut buf);
        if PyErr::occurred(py) {
            return Err(PyErr::fetch(py));
        }
        let read = read?;
        if read == 0 {
            return Ok(None);
        }
        buf.truncate(read);
        Ok(Some(PyBytes::new(py, &buf).to_object(py)))
    }
}

#[pyfunction]
fn IterableFile(py_iterable: PyObject) -> PyResult<PyObject> {
    Python::with_gil(|py| {
        let py_iter = py_iterable.call_method0(py, "__iter__")?;
        let line_iter: Box<dyn Iterator<Item = std::io::Result<Vec<u8>>> + Send> = Box::new(
            std::iter::from_fn(move || -> Option<std::io::Result<Vec<u8>>> {
                Python::with_gil(
                    |py| match py_iter.downcast::<PyIterator>(py).unwrap().next() {
                        None => None,
                        Some(Err(err)) => {
                            PyErr::restore(err.clone_ref(py), py);
                            Some(Err(std::io::Error::new(
                                std::io::ErrorKind::Other,
                                err.to_string(),
                            )))
                        }
                        Some(Ok(obj)) => match obj.downcast::<PyBytes>() {
                            Err(err) => {
                                PyErr::restore(
                                    PyTypeError::new_err("unable to convert to bytes"),
                                    py,
                                );
                                Some(Err(std::io::Error::new(
                                    std::io::ErrorKind::Other,
                                    err.to_string(),
                                )))
                            }
                            Ok(bytes) => Some(Ok(bytes.as_bytes().to_vec())),
                        },
                    },
                )
            }),
        );

        let f = breezy_osutils::iterablefile::IterableFile::new(line_iter);

        Ok(PyIterableFile {
            inner: f,
            closed: false,
        }
        .into_py(py))
    })
}

#[pyfunction]
fn check_text_path(path: &PyAny) -> PyResult<()> {
    let path = extract_path(path)?;
    if !breezy_osutils::textfile::check_text_path(path.as_path())? {
        Err(BinaryFile::new_err(()))
    } else {
        Ok(())
    }
}

#[pyfunction]
fn check_text_lines(py: Python, lines: &PyAny) -> PyResult<()> {
    let mut py_iter = lines.iter()?;
    let line_iter = std::iter::from_fn(|| {
        let line = py_iter.next();
        match line {
            Some(Ok(line)) => Some(line.extract::<Vec<u8>>().unwrap()),
            Some(Err(err)) => {
                PyErr::restore(err, py);
                None
            }
            None => None,
        }
    });

    let result = breezy_osutils::textfile::check_text_lines(line_iter);
    if PyErr::occurred(py) {
        return Err(PyErr::fetch(py));
    }
    if !result {
        Err(BinaryFile::new_err(()))
    } else {
        Ok(())
    }
}

#[pyfunction]
fn format_date_with_offset_in_original_timezone(
    py: Python,
    date: PyObject,
    offset: Option<PyObject>,
) -> PyResult<String> {
    let date = if let Ok(date) = date.extract::<f64>(py) {
        date as i64
    } else if let Ok(date) = date.extract::<i64>(py) {
        date
    } else {
        return Err(PyValueError::new_err("date must be a float or int"));
    };
    let offset = if let Some(offset) = offset {
        if let Ok(offset) = offset.extract::<f64>(py) {
            offset as i64
        } else if let Ok(offset) = offset.extract::<i64>(py) {
            offset
        } else {
            return Err(PyValueError::new_err("offset must be a float or int"));
        }
    } else {
        0
    };
    Ok(breezy_osutils::time::format_date_with_offset_in_original_timezone(date, offset))
}

#[pyfunction]
fn format_date(
    py: Python,
    t: PyObject,
    offset: Option<PyObject>,
    timezone: Option<&str>,
    date_fmt: Option<&str>,
    show_offset: Option<bool>,
) -> PyResult<String> {
    let t = if let Ok(t) = t.extract::<f64>(py) {
        t as i64
    } else if let Ok(t) = t.extract::<i64>(py) {
        t
    } else {
        return Err(PyValueError::new_err("t must be a float or int"));
    };
    let timezone = breezy_osutils::time::Timezone::from(timezone.unwrap_or("original"));
    if timezone.is_none() {
        return Err(UnsupportedTimezoneFormat::new_err("unsupported timezone"));
    }
    let offset = if let Some(offset) = offset {
        if let Ok(offset) = offset.extract::<f64>(py) {
            Some(offset as i64)
        } else if let Ok(offset) = offset.extract::<i64>(py) {
            Some(offset)
        } else {
            return Err(PyValueError::new_err("offset must be a float or int"));
        }
    } else {
        None
    };
    let timezone = timezone.unwrap();
    Ok(breezy_osutils::time::format_date(
        t,
        offset,
        timezone,
        date_fmt,
        show_offset.unwrap_or(true),
    ))
}

#[pyfunction]
fn format_highres_date(py: Python, t: PyObject, offset: Option<PyObject>) -> PyResult<String> {
    let t = if let Ok(t) = t.extract::<f64>(py) {
        t
    } else if let Ok(t) = t.extract::<i64>(py) {
        t as f64
    } else {
        return Err(PyValueError::new_err("t must be a float or int"));
    };
    let offset = if let Some(offset) = offset {
        if let Ok(offset) = offset.extract::<f64>(py) {
            Some(offset as i32)
        } else if let Ok(offset) = offset.extract::<i64>(py) {
            Some(offset as i32)
        } else {
            return Err(PyValueError::new_err("offset must be a float or int"));
        }
    } else {
        None
    };
    Ok(breezy_osutils::time::format_highres_date(t, offset))
}

#[pyfunction]
fn unpack_highres_date(date: &str) -> PyResult<(f64, i32)> {
    breezy_osutils::time::unpack_highres_date(date).map_err(PyValueError::new_err)
}

#[pyfunction]
#[cfg(unix)]
fn get_umask() -> PyResult<u32> {
    Ok(breezy_osutils::get_umask().bits())
}

#[pyfunction]
fn kind_marker(kind: &str) -> &str {
    match kind {
        "file" => Kind::File,
        "directory" => Kind::Directory,
        "symlink" => Kind::Symlink,
        "tree-reference" => Kind::TreeReference,
        _ => return "",
    }
    .marker()
}

#[pyfunction]
fn make_writable(path: PathBuf) -> PyResult<()> {
    Ok(breezy_osutils::file::make_writable(path)?)
}

#[pyfunction]
fn make_readonly(path: PathBuf) -> PyResult<()> {
    Ok(breezy_osutils::file::make_readonly(path)?)
}

#[pyfunction]
fn compact_date(py: Python, when: PyObject) -> PyResult<String> {
    let when = if let Ok(when) = when.extract::<f64>(py) {
        when as u64
    } else if let Ok(when) = when.extract::<i64>(py) {
        when as u64
    } else {
        return Err(PyValueError::new_err("when must be a float or int"));
    };
    Ok(breezy_osutils::time::compact_date(when))
}

#[pyfunction]
fn chmod_if_possible(path: PathBuf, mode: u32) -> PyResult<()> {
    use std::os::unix::fs::PermissionsExt;
    Ok(breezy_osutils::file::chmod_if_possible(
        path,
        Permissions::from_mode(mode),
    )?)
}

#[pyfunction]
fn quotefn(filename: &str) -> String {
    breezy_osutils::path::quotefn(filename)
}

/// Copy usr/grp ownership from src file/dir to dst file/dir.
///
/// If src is None, the containing directory is used as source. If chown
/// fails, the error is ignored and a warning is printed.
#[pyfunction]
fn copy_ownership_from_path(dst: PathBuf, src: Option<PathBuf>) -> PyResult<()> {
    Ok(breezy_osutils::file::copy_ownership_from_path(
        dst,
        src.as_deref(),
    )?)
}

#[pyfunction]
fn link_or_copy(src: PathBuf, dst: PathBuf) -> PyResult<()> {
    Ok(breezy_osutils::file::link_or_copy(src, dst)?)
}

/// Return if the filesystem at path supports the creation of hardlinks.
#[pyfunction]
fn supports_hardlinks(path: PathBuf) -> Option<bool> {
    breezy_osutils::mounts::supports_hardlinks(path)
}

/// Return if the filesystem at path supports the creation of symbolic links.
#[pyfunction]
fn supports_symlinks(path: PathBuf) -> Option<bool> {
    breezy_osutils::mounts::supports_symlinks(path)
}

#[pyfunction]
fn supports_posix_readonly() -> bool {
    breezy_osutils::mounts::supports_posix_readonly()
}

/// Return if filesystem at path supports executable bit.
///
/// Args:
///   path: Path for which to check the file system
/// Returns: boolean indicating whether executable bit can be stored/relied upon
#[pyfunction]
fn supports_executable(path: PathBuf) -> Option<bool> {
    breezy_osutils::mounts::supports_executable(path)
}

/// Read an fstab-style file and extract mountpoint+filesystem information.
///
/// Args:
///   path: Path to read from
/// Returns:
///   Tuples with mountpoints (as bytestrings) and filesystem names
#[pyfunction]
fn read_mtab(py: Python, path: PathBuf) -> PyResult<PyObject> {
    let it: Vec<breezy_osutils::mounts::MountEntry> =
        breezy_osutils::mounts::read_mtab(path).collect();
    let list = PyList::empty(py);
    for entry in it {
        let tuple = PyTuple::new(py, &[entry.path.into_py(py), entry.fs_type.into_py(py)]);
        list.append(tuple)?;
    }
    Ok(list.as_ref().iter()?.to_object(py))
}

#[pyfunction]
fn get_fs_type(path: PathBuf) -> PyResult<Option<String>> {
    Ok(breezy_osutils::mounts::get_fs_type(path))
}

#[pyfunction]
fn copy_tree(from_path: PathBuf, to_path: PathBuf) -> PyResult<()> {
    Ok(breezy_osutils::file::copy_tree(from_path, to_path)?)
}

#[pyfunction]
fn abspath(path: PathBuf) -> PyResult<PathBuf> {
    breezy_osutils::path::abspath(path.as_path()).map_err(|e| e.into())
}

#[pyfunction(name = "abspath")]
fn posix_abspath(path: PathBuf) -> PyResult<PathBuf> {
    breezy_osutils::path::posix::abspath(path.as_path()).map_err(|e| e.into())
}

#[pyfunction(name = "abspath")]
fn win32_abspath(path: PathBuf) -> PyResult<PathBuf> {
    breezy_osutils::path::win32::abspath(path.as_path()).map_err(|e| e.into())
}

#[cfg(unix)]
#[pyfunction]
fn kind_from_mode(mode: u32) -> &'static str {
    use nix::sys::stat::SFlag;
    breezy_osutils::file::kind_from_mode(SFlag::from_bits_truncate(mode))
}

#[pyfunction]
fn delete_any(path: PathBuf) -> PyResult<()> {
    Ok(breezy_osutils::file::delete_any(path)?)
}

#[pyfunction]
fn get_host_name() -> PyResult<String> {
    Ok(breezy_osutils::get_host_name()?)
}

#[pyfunction]
fn local_concurrency(use_cache: Option<bool>) -> usize {
    breezy_osutils::local_concurrency(use_cache.unwrap_or(true))
}

#[pyfunction]
fn pumpfile(from_file: PyObject, to_file: PyObject, read_size: Option<u64>) -> PyResult<u64> {
    let mut from_file = PyBinaryFile::from(from_file);
    let mut to_file = PyBinaryFile::from(to_file);

    Ok(breezy_osutils::pumpfile(
        &mut from_file,
        &mut to_file,
        read_size,
    )?)
}

#[pyfunction]
fn contains_whitespace(py: Python, text: PyObject) -> PyResult<bool> {
    if let Ok(s) = text.extract::<&str>(py) {
        Ok(breezy_osutils::contains_whitespace(s))
    } else if let Ok(s) = text.extract::<&[u8]>(py) {
        Ok(breezy_osutils::contains_whitespace_bytes(s))
    } else {
        Err(PyTypeError::new_err("text must be str or bytes"))
    }
}

#[pyfunction]
fn relpath(path: PathBuf, start: PathBuf) -> PyResult<PathBuf> {
    match breezy_osutils::path::relpath(path.as_path(), start.as_path()) {
        None => Err(PathNotChild::new_err((start, path))),
        Some(p) => Ok(p),
    }
}

#[pyfunction(name = "normpath")]
fn posix_normpath(path: PathBuf) -> PyResult<PathBuf> {
    Ok(breezy_osutils::path::posix::normpath(path.as_path()))
}

#[pyfunction(name = "normpath")]
fn win32_normpath(path: PathBuf) -> PyResult<PathBuf> {
    Ok(breezy_osutils::path::win32::normpath(path.as_path()))
}

#[pyfunction]
fn contains_linebreaks(text: &str) -> bool {
    breezy_osutils::contains_linebreaks(text)
}

#[pyfunction]
fn normpath(path: PathBuf) -> PyResult<PathBuf> {
    Ok(breezy_osutils::path::normpath(path.as_path()))
}

#[pyfunction]
fn realpath(path: PathBuf) -> PyResult<PathBuf> {
    Ok(breezy_osutils::path::realpath(path.as_path())?)
}

#[pyfunction]
fn normalizepath(path: PathBuf) -> PyResult<PathBuf> {
    Ok(breezy_osutils::path::normalizepath(path.as_path())?)
}

#[pyfunction]
fn dereference_path(path: PathBuf) -> std::io::Result<PathBuf> {
    breezy_osutils::path::dereference_path(path.as_path())
}

#[pyfunction]
fn pump_string_file(data: &[u8], file: PyObject, segment_size: Option<usize>) -> PyResult<()> {
    let mut file = PyBinaryFile::from(file);
    Ok(breezy_osutils::pump_string_file(
        data,
        &mut file,
        segment_size,
    )?)
}

/// Return path with directory separators changed to forward slashes
#[pyfunction(name = "fix_separators")]
fn win32_fix_separators(path: PathBuf) -> PathBuf {
    breezy_osutils::path::win32::fix_separators(path.as_path())
}

/// Force drive letters to be consistent.
///
/// win32 is inconsistent whether it returns lower or upper case
/// and even if it was consistent the user might type the other
/// so we force it to uppercase running python.exe under cmd.exe return capital C:\\ running win32
/// python inside a cygwin shell returns lowercase c:\\
#[pyfunction(name = "fixdrive")]
fn win32_fixdrive(path: PathBuf) -> PathBuf {
    breezy_osutils::path::win32::fixdrive(path.as_path())
}

#[pyfunction(name = "getcwd")]
fn win32_getcwd() -> PyResult<PathBuf> {
    Ok(breezy_osutils::path::win32::getcwd()?)
}

#[pyclass]
struct FileIterator {
    input_file: PyObject,
    read_size: usize,
}

#[pymethods]
impl FileIterator {
    #[new]
    fn new(input_file: PyObject, read_size: Option<usize>) -> Self {
        FileIterator {
            input_file,
            read_size: read_size.unwrap_or(32768),
        }
    }

    fn __iter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __next__(&mut self, py: Python) -> PyResult<Option<PyObject>> {
        let result = self.input_file.call_method1(py, "read", (self.read_size,));
        match result {
            Ok(buf) if buf.is_none(py) => Ok(None),
            Ok(buf) if buf.as_ref(py).len()? == 0 => Ok(None),
            Ok(buf) => Ok(Some(buf)),
            Err(e) => Err(e),
        }
    }
}

#[pyfunction]
fn file_iterator(py: Python, input_file: PyObject, read_size: Option<usize>) -> PyResult<PyObject> {
    let iterator = FileIterator::new(input_file, read_size);
    Ok(iterator.into_py(py))
}

/// Returns the terminal size as (width, height).
///
/// Args:
///   width: Default value for width.
///   height: Default value for height.
///
/// This is defined specifically for each OS and query the size of the controlling
/// terminal. If any error occurs, the provided default values should be returned.
#[pyfunction]
fn terminal_size() -> PyResult<(u16, u16)> {
    Ok(breezy_osutils::terminal::terminal_size()?)
}

#[pyfunction]
fn has_ansi_colors() -> bool {
    breezy_osutils::terminal::has_ansi_colors()
}

/// Make sure a local directory exists and is empty.
///
/// If it does not exist, it is created.  If it exists and is not empty,
/// DirectoryNotEmpty is raised.
#[pyfunction]
fn ensure_empty_directory_exists(path: PathBuf) -> PyResult<()> {
    match breezy_osutils::file::ensure_empty_directory_exists(path.as_path()) {
        Ok(()) => Ok(()),
        Err(ref e)
            if e.kind() == std::io::ErrorKind::Other && e.to_string().contains(" not empty") =>
        {
            Err(DirectoryNotEmpty::new_err(path))
        }
        Err(e) => Err(e.into()),
    }
}

#[pyfunction]
fn get_home_dir() -> PyResult<Option<PathBuf>> {
    Ok(breezy_osutils::get_home_dir())
}

#[pyfunction]
fn get_user_encoding() -> Option<String> {
    breezy_osutils::get_user_encoding()
}

fn string_to_color(name: &str) -> PyResult<&dyn Color> {
    match name {
        "darkblack" => Ok(&termion::color::Black),
        "darkred" => Ok(&termion::color::Red),
        "darkgreen" => Ok(&termion::color::Green),
        "darkyellow" => Ok(&termion::color::Yellow),
        "darkblue" => Ok(&termion::color::Blue),
        "darkmagenta" => Ok(&termion::color::Magenta),
        "darkcyan" => Ok(&termion::color::Cyan),
        "darkwhite" => Ok(&termion::color::White),
        "yellow" => Ok(&termion::color::LightYellow),
        "black" => Ok(&termion::color::LightBlack),
        "red" => Ok(&termion::color::LightRed),
        "green" => Ok(&termion::color::LightGreen),
        "blue" => Ok(&termion::color::LightBlue),
        "magenta" => Ok(&termion::color::LightMagenta),
        "cyan" => Ok(&termion::color::LightCyan),
        "white" => Ok(&termion::color::LightWhite),
        _ => Err(PyValueError::new_err(format!(
            "Invalid color name: {}",
            name
        ))),
    }
}

#[pyfunction]
fn color_exists(name: &str) -> bool {
    string_to_color(name).is_ok()
}

#[pyfunction]
fn colorstring(
    py: Python,
    text: &[u8],
    fgcolor: Option<&str>,
    bgcolor: Option<&str>,
) -> PyResult<PyObject> {
    let fgcolor = fgcolor.map(string_to_color).transpose()?;
    let bgcolor = bgcolor.map(string_to_color).transpose()?;

    Ok(PyBytes::new(
        py,
        &breezy_osutils::terminal::colorstring(text, fgcolor, bgcolor),
    )
    .into_py(py))
}

#[pyfunction]
fn lexists(path: PathBuf) -> PyResult<bool> {
    Ok(breezy_osutils::file::lexists(path.as_path())?)
}

fn extract_osstring(py: Python, obj: PyObject) -> PyResult<OsString> {
    if let Ok(s) = obj.extract::<OsString>(py) {
        Ok(s)
    } else if let Ok(s) = obj.extract::<Vec<u8>>(py) {
        Ok(OsString::from_vec(s))
    } else {
        Err(PyTypeError::new_err(format!(
            "Expected str, or bytes, got {}",
            obj.as_ref(py).get_type().name()?
        )))
    }
}

#[pyfunction]
fn joinpath(py: Python, parts: Vec<PyObject>) -> PyResult<PathBuf> {
    let parts = parts
        .into_iter()
        .map(|p| extract_osstring(py, p))
        .collect::<PyResult<Vec<_>>>()?;
    match breezy_osutils::path::joinpath(
        parts
            .iter()
            .map(|p| p.as_os_str())
            .collect::<Vec<_>>()
            .as_slice(),
    ) {
        Ok(path) => Ok(path),
        Err(e) => Err(PyValueError::new_err(format!(
            "Invalid path segment: {}",
            e.0
        ))),
    }
}

#[pyfunction(signature = (*args))]
fn pathjoin(py: Python, args: Vec<PyObject>) -> PyResult<PyObject> {
    let return_bytes = args[0].as_ref(py).is_instance_of::<PyBytes>();
    let parts = args
        .into_iter()
        .map(|p| extract_osstring(py, p))
        .collect::<PyResult<Vec<_>>>()?;

    let ret: PathBuf = breezy_osutils::path::pathjoin(
        parts
            .iter()
            .map(|p| p.as_os_str())
            .collect::<Vec<_>>()
            .as_slice(),
    );

    if return_bytes {
        use std::os::unix::ffi::OsStrExt;
        Ok(PyBytes::new(py, ret.as_path().as_os_str().as_bytes()).into_py(py))
    } else {
        Ok(ret.into_py(py))
    }
}

#[pyfunction]
fn splitpath(path: PathBuf) -> PyResult<Vec<String>> {
    match breezy_osutils::path::splitpath(path.to_str().unwrap()) {
        Ok(parts) => Ok(parts.iter().map(|p| p.to_string()).collect()),
        Err(e) => Err(PyValueError::new_err(format!(
            "Invalid path segment: {}",
            e.0
        ))),
    }
}

#[pyfunction]
fn get_user_name() -> PyResult<String> {
    Ok(breezy_osutils::get_user_name())
}

#[cfg(unix)]
#[pyfunction]
fn is_local_pid_dead(pid: i32) -> PyResult<bool> {
    #[cfg(unix)]
    use nix::unistd::Pid;

    Ok(breezy_osutils::is_local_pid_dead(Pid::from_raw(pid)))
}

#[pyfunction]
fn compare_files(a: PyObject, b: PyObject) -> PyResult<bool> {
    let a = PyBinaryFile::from(a);
    let b = PyBinaryFile::from(b);
    Ok(breezy_osutils::file::compare_files(a, b)?)
}

#[pyfunction]
fn readlink(path: PathBuf) -> PyResult<PathBuf> {
    path.read_link().map_err(|e| e.into())
}

#[pyfunction]
fn getchar() -> PyResult<char> {
    Ok(breezy_osutils::terminal::getchar()?)
}

#[pyfunction]
fn isdir(path: PathBuf) -> PyResult<bool> {
    Ok(breezy_osutils::file::isdir(path.as_path()))
}

#[pymodule]
fn _osutils_rs(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(chunks_to_lines))?;
    m.add_wrapped(wrap_pyfunction!(chunks_to_lines_iter))?;
    m.add_wrapped(wrap_pyfunction!(sha_file_by_name))?;
    m.add_wrapped(wrap_pyfunction!(sha_string))?;
    m.add_wrapped(wrap_pyfunction!(sha_strings))?;
    m.add_wrapped(wrap_pyfunction!(sha_file))?;
    m.add_wrapped(wrap_pyfunction!(size_sha_file))?;
    m.add_wrapped(wrap_pyfunction!(normalized_filename))?;
    m.add_wrapped(wrap_pyfunction!(_inaccessible_normalized_filename))?;
    m.add_wrapped(wrap_pyfunction!(_accessible_normalized_filename))?;
    m.add_wrapped(wrap_pyfunction!(normalizes_filenames))?;
    m.add_wrapped(wrap_pyfunction!(is_inside))?;
    m.add_wrapped(wrap_pyfunction!(is_inside_any))?;
    m.add_wrapped(wrap_pyfunction!(is_inside_or_parent_of_any))?;
    m.add_wrapped(wrap_pyfunction!(minimum_path_selection))?;
    m.add_wrapped(wrap_pyfunction!(set_or_unset_env))?;
    m.add_wrapped(wrap_pyfunction!(parent_directories))?;
    m.add_wrapped(wrap_pyfunction!(available_backup_name))?;
    m.add_wrapped(wrap_pyfunction!(find_executable_on_path))?;
    m.add_wrapped(wrap_pyfunction!(legal_path))?;
    m.add_wrapped(wrap_pyfunction!(check_legal_path))?;
    m.add_wrapped(wrap_pyfunction!(local_time_offset))?;
    m.add_wrapped(wrap_pyfunction!(format_local_date))?;
    m.add_wrapped(wrap_pyfunction!(rand_chars))?;
    m.add_wrapped(wrap_pyfunction!(IterableFile))?;
    m.add_wrapped(wrap_pyfunction!(check_text_path))?;
    m.add_wrapped(wrap_pyfunction!(check_text_lines))?;
    m.add_wrapped(wrap_pyfunction!(file_iterator))?;
    m.add_wrapped(wrap_pyfunction!(
        format_date_with_offset_in_original_timezone
    ))?;
    m.add_wrapped(wrap_pyfunction!(format_date))?;
    m.add_wrapped(wrap_pyfunction!(format_highres_date))?;
    m.add_wrapped(wrap_pyfunction!(unpack_highres_date))?;
    m.add_wrapped(wrap_pyfunction!(kind_marker))?;
    m.add_wrapped(wrap_pyfunction!(split_lines))?;
    m.add_wrapped(wrap_pyfunction!(make_writable))?;
    m.add_wrapped(wrap_pyfunction!(make_readonly))?;
    m.add_wrapped(wrap_pyfunction!(compact_date))?;
    m.add_wrapped(wrap_pyfunction!(chmod_if_possible))?;
    m.add_wrapped(wrap_pyfunction!(quotefn))?;
    m.add_wrapped(wrap_pyfunction!(copy_ownership_from_path))?;
    m.add_wrapped(wrap_pyfunction!(link_or_copy))?;
    m.add_wrapped(wrap_pyfunction!(supports_hardlinks))?;
    m.add_wrapped(wrap_pyfunction!(supports_symlinks))?;
    m.add_wrapped(wrap_pyfunction!(supports_executable))?;
    m.add_wrapped(wrap_pyfunction!(supports_posix_readonly))?;
    m.add_wrapped(wrap_pyfunction!(read_mtab))?;
    m.add_wrapped(wrap_pyfunction!(get_fs_type))?;
    m.add_wrapped(wrap_pyfunction!(copy_tree))?;
    m.add_wrapped(wrap_pyfunction!(abspath))?;
    let win32m = PyModule::new(py, "win32")?;
    win32m.add_wrapped(wrap_pyfunction!(win32_abspath))?;
    win32m.add_wrapped(wrap_pyfunction!(win32_normpath))?;
    win32m.add_wrapped(wrap_pyfunction!(win32_fix_separators))?;
    win32m.add_wrapped(wrap_pyfunction!(win32_fixdrive))?;
    win32m.add_wrapped(wrap_pyfunction!(win32_getcwd))?;
    m.add_submodule(win32m)?;
    let posixm = PyModule::new(py, "posix")?;
    posixm.add_wrapped(wrap_pyfunction!(posix_abspath))?;
    posixm.add_wrapped(wrap_pyfunction!(posix_normpath))?;
    m.add_submodule(posixm)?;
    #[cfg(unix)]
    m.add_wrapped(wrap_pyfunction!(get_umask))?;
    #[cfg(unix)]
    m.add_wrapped(wrap_pyfunction!(kind_from_mode))?;
    m.add_wrapped(wrap_pyfunction!(delete_any))?;
    m.add_wrapped(wrap_pyfunction!(get_host_name))?;
    m.add_wrapped(wrap_pyfunction!(local_concurrency))?;
    m.add_wrapped(wrap_pyfunction!(pumpfile))?;
    m.add_wrapped(wrap_pyfunction!(contains_whitespace))?;
    m.add_wrapped(wrap_pyfunction!(contains_linebreaks))?;
    m.add_wrapped(wrap_pyfunction!(relpath))?;
    m.add_wrapped(wrap_pyfunction!(normpath))?;
    m.add_wrapped(wrap_pyfunction!(pump_string_file))?;
    m.add_wrapped(wrap_pyfunction!(realpath))?;
    m.add_wrapped(wrap_pyfunction!(normalizepath))?;
    m.add_wrapped(wrap_pyfunction!(dereference_path))?;
    m.add_wrapped(wrap_pyfunction!(terminal_size))?;
    m.add_wrapped(wrap_pyfunction!(has_ansi_colors))?;
    m.add_wrapped(wrap_pyfunction!(ensure_empty_directory_exists))?;
    m.add_wrapped(wrap_pyfunction!(get_user_encoding))?;
    m.add(
        "MIN_ABS_PATHLENGTH",
        breezy_osutils::path::MIN_ABS_PATHLENGTH,
    )?;
    m.add(
        "UnsupportedTimezoneFormat",
        py.get_type::<UnsupportedTimezoneFormat>(),
    )?;
    m.add_wrapped(wrap_pyfunction!(get_home_dir))?;
    m.add_wrapped(wrap_pyfunction!(colorstring))?;
    m.add_wrapped(wrap_pyfunction!(color_exists))?;
    m.add_wrapped(wrap_pyfunction!(lexists))?;
    m.add_wrapped(wrap_pyfunction!(pathjoin))?;
    m.add_wrapped(wrap_pyfunction!(joinpath))?;
    m.add_wrapped(wrap_pyfunction!(splitpath))?;
    m.add_wrapped(wrap_pyfunction!(is_local_pid_dead))?;
    m.add_wrapped(wrap_pyfunction!(get_user_name))?;
    m.add_wrapped(wrap_pyfunction!(compare_files))?;
    m.add_wrapped(wrap_pyfunction!(readlink))?;
    m.add_wrapped(wrap_pyfunction!(getchar))?;
    m.add_wrapped(wrap_pyfunction!(isdir))?;
    Ok(())
}
