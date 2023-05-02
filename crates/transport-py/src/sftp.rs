use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyType};

use std::collections::VecDeque;
use std::io::{Read, Seek};
use std::sync::Arc;

create_exception!(breezy._transport_rs, SFTPError, PyException);
import_exception!(breezy.transport, NoSuchFile);
import_exception!(breezy.errors, PermissionDenied);

#[pyclass]
struct SFTPAttributes(breezy_transport::sftp::Attributes);

#[pymethods]
impl SFTPAttributes {
    #[new]
    fn new() -> Self {
        Self(breezy_transport::sftp::Attributes::new())
    }

    #[getter]
    fn get_st_mode(&self) -> Option<u32> {
        self.0.permissions
    }

    #[setter]
    fn set_st_mode(&mut self, mode: Option<u32>) {
        self.0.permissions = mode;
    }

    #[getter]
    fn get_st_size(&self) -> Option<u64> {
        self.0.size
    }

    #[setter]
    fn set_st_size(&mut self, size: Option<u64>) {
        self.0.size = size;
    }
}

#[pyclass]
struct SFTPClient {
    sftp: Arc<breezy_transport::sftp::SftpClient>,
    cwd: Option<String>,
}

fn sftp_error_to_py_err(e: breezy_transport::sftp::Error, path: Option<&str>) -> PyErr {
    match e {
        breezy_transport::sftp::Error::Io(e) => e.into(),
        breezy_transport::sftp::Error::Eof(_, _) => {
            std::io::Error::from(std::io::ErrorKind::UnexpectedEof).into()
        }
        breezy_transport::sftp::Error::NoSuchFile(msg, _lang) => {
            NoSuchFile::new_err((path.map(|p| p.to_string()), msg))
        }
        breezy_transport::sftp::Error::PermissionDenied(msg, _) => {
            PermissionDenied::new_err((path.map(|p| p.to_string()), msg))
        }
        breezy_transport::sftp::Error::Failure(msg, _lang) => SFTPError::new_err(msg),
        _ => SFTPError::new_err(format!("{:?}", e)),
    }
}

#[pyclass]
struct SFTPFile {
    sftp: Arc<breezy_transport::sftp::SftpClient>,
    file: breezy_transport::sftp::File,
    offset: u64,
}

impl SFTPClient {
    fn _adjust_cwd(&self, path: &str) -> String {
        if self.cwd.is_none() {
            return path.to_string();
        }

        if path.starts_with('/') {
            return path.to_string();
        }

        if self.cwd == Some("/".to_owned()) {
            return format!("/{}", path);
        }

        format!("{}/{}", self.cwd.as_ref().unwrap(), path)
    }
}

#[pymethods]
impl SFTPFile {
    fn block(&mut self, py: Python, offset: u64, length: u64, lockmask: u32) -> PyResult<()> {
        py.allow_threads(|| self.sftp.block(&self.file, offset, length, lockmask))
            .map_err(|e| sftp_error_to_py_err(e, None))
    }

    fn unblock(&mut self, py: Python, offset: u64, length: u64) -> PyResult<()> {
        py.allow_threads(|| self.sftp.unblock(&self.file, offset, length))
            .map_err(|e| sftp_error_to_py_err(e, None))
    }

    fn setstat(&mut self, py: Python, attr: &SFTPAttributes) -> PyResult<()> {
        py.allow_threads(|| self.sftp.fsetstat(&self.file, &attr.0))
            .map_err(|e| sftp_error_to_py_err(e, None))
    }

    fn stat(&mut self, py: Python, flags: Option<u32>) -> PyResult<SFTPAttributes> {
        py.allow_threads(|| self.sftp.fstat(&self.file, flags).map(SFTPAttributes))
            .map_err(|e| sftp_error_to_py_err(e, None))
    }

    fn flush(&mut self, py: Python) -> PyResult<()> {
        Ok(())
    }

    fn pwrite(&mut self, py: Python, offset: u64, data: &[u8]) -> PyResult<()> {
        py.allow_threads(|| self.sftp.pwrite(&self.file, offset, data))
            .map_err(|e| sftp_error_to_py_err(e, None))
    }

    fn pread(&mut self, py: Python, offset: u64, length: u32) -> PyResult<PyObject> {
        py.allow_threads(|| self.sftp.pread(&self.file, offset, length))
            .map_err(|e| sftp_error_to_py_err(e, None))
            .map(|b| PyBytes::new(py, &b).into())
    }

    fn close(&mut self, py: Python) -> PyResult<()> {
        py.allow_threads(|| self.sftp.fclose(&self.file))
            .map_err(|e| sftp_error_to_py_err(e, None))
    }

    fn seekable(&self) -> bool {
        true
    }

    fn tell(&self) -> u64 {
        self.offset
    }

    fn seek(&mut self, py: Python, offset: i64, whence: u32) -> PyResult<u64> {
        let size = self.stat(py, None)?.0.size.unwrap();
        let new_offset = match whence {
            // SEEK_SET
            0 => offset,
            // SEEK_CUR
            1 => self.offset as i64 + offset,
            // SEEK_END
            2 => size as i64 - offset,
            _ => {
                return Err(PyValueError::new_err(("Invalid whence",)));
            }
        };

        if new_offset < 0 {
            return Err(PyValueError::new_err((format!(
                "Negative offset: {}",
                new_offset
            ),)));
        }

        self.offset = new_offset as u64;
        Ok(self.offset)
    }

    fn readv(&mut self, py: Python, offsets: Vec<(u64, u32)>) -> PyResult<PyObject> {
        #[pyclass]
        struct ReadvIter {
            offsets: VecDeque<(u64, u32)>,
            sftp: Arc<breezy_transport::sftp::SftpClient>,
            file: breezy_transport::sftp::File,
        }

        #[pymethods]
        impl ReadvIter {
            fn __iter__(slf: PyRef<Self>) -> Py<Self> {
                slf.into()
            }

            fn __next__(&mut self, py: Python) -> PyResult<Option<PyObject>> {
                if let Some((offset, length)) = self.offsets.pop_front() {
                    match py.allow_threads(|| self.sftp.pread(&self.file, offset, length)) {
                        Ok(data) => Ok(Some(PyBytes::new(py, &data).into())),
                        Err(breezy_transport::sftp::Error::Eof(_, _)) => {
                            Ok(Some(PyBytes::new(py, &[]).into()))
                        }
                        Err(e) => Err(sftp_error_to_py_err(e, None)),
                    }
                } else {
                    Ok(None)
                }
            }
        }

        Ok(ReadvIter {
            offsets: VecDeque::from(offsets),
            sftp: Arc::clone(&self.sftp),
            file: self.file.clone(),
        }
        .into_py(py))
    }

    fn read(&mut self, py: Python, length: Option<u32>) -> PyResult<PyObject> {
        let ret = if let Some(length) = length {
            py.allow_threads(|| self.sftp.pread(&self.file, self.offset, length))
        } else {
            let length = self.stat(py, None)?.0.size.unwrap();
            if length == 0 {
                return Ok(PyBytes::new(py, &[]).into_py(py));
            }
            py.allow_threads(|| {
                self.sftp
                    .pread(&self.file, self.offset, (length - self.offset) as u32)
            })
        };
        match ret {
            Ok(data) => {
                self.offset += data.len() as u64;
                Ok(PyBytes::new(py, data.as_slice()).into_py(py))
            }
            Err(breezy_transport::sftp::Error::Eof(_, _)) => Ok(PyBytes::new(py, &[]).into_py(py)),
            Err(e) => Err(sftp_error_to_py_err(e, None)),
        }
    }

    fn write(&mut self, py: Python, data: &[u8]) -> PyResult<()> {
        py.allow_threads(|| self.sftp.pwrite(&self.file, self.offset, data))
            .map_err(|e| sftp_error_to_py_err(e, None))?;
        self.offset += data.len() as u64;
        Ok(())
    }

    fn __enter__(slf: PyRef<Self>) -> Py<Self> {
        slf.into()
    }

    fn __exit__(
        &mut self,
        py: Python,
        _exc_type: Option<&PyType>,
        _exc_val: Option<&PyAny>,
        _exc_tb: Option<&PyAny>,
    ) -> PyResult<bool> {
        self.close(py)?;
        Ok(false)
    }
}

#[pyclass]
struct SFTPDir(
    Arc<breezy_transport::sftp::SftpClient>,
    breezy_transport::sftp::Directory,
);

#[pymethods]
impl SFTPDir {
    fn readdir(&mut self, py: Python) -> PyResult<Option<Vec<(String, String, SFTPAttributes)>>> {
        match py.allow_threads(|| {
            self.0.readdir(&self.1).map(|e| {
                e.into_iter()
                    .map(|(k, l, v)| (k, l, SFTPAttributes(v)))
                    .collect::<Vec<_>>()
            })
        }) {
            Ok(v) => Ok(Some(v)),
            Err(breezy_transport::sftp::Error::Eof(_, _)) => Ok(None),
            Err(e) => Err(sftp_error_to_py_err(e, None)),
        }
    }

    fn close(&mut self, py: Python) -> PyResult<()> {
        py.allow_threads(|| self.0.closedir(&self.1))
            .map_err(|e| sftp_error_to_py_err(e, None))
    }
}

#[pymethods]
impl SFTPClient {
    #[new]
    fn new(py: Python, fd: i32) -> PyResult<Self> {
        let session = py.allow_threads(|| breezy_transport::sftp::SftpClient::from_fd(fd))?;
        Ok(Self {
            sftp: Arc::new(session),
            cwd: None,
        })
    }

    fn mkdir(&mut self, py: Python, path: &str, mode: Option<u32>) -> PyResult<()> {
        let path = self._adjust_cwd(path);
        let mut attr = breezy_transport::sftp::Attributes::new();
        attr.permissions = Some(mode.unwrap_or(0o777) | 0o40000);
        py.allow_threads(|| self.sftp.mkdir(path.as_str(), &attr))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))
    }

    fn extended(&mut self, py: Python, extension: &str, data: &[u8]) -> PyResult<Option<Vec<u8>>> {
        py.allow_threads(|| self.sftp.extended(extension, data))
            .map_err(|e| sftp_error_to_py_err(e, None))
    }

    fn lstat(&mut self, py: Python, path: &str, flags: Option<u32>) -> PyResult<SFTPAttributes> {
        let path = self._adjust_cwd(path);
        py.allow_threads(|| self.sftp.lstat(path.as_str(), flags))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))
            .map(SFTPAttributes)
    }

    fn stat(&mut self, py: Python, path: &str, flags: Option<u32>) -> PyResult<SFTPAttributes> {
        let path = self._adjust_cwd(path);
        py.allow_threads(|| self.sftp.stat(path.as_str(), flags))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))
            .map(SFTPAttributes)
    }

    fn chmod(&mut self, py: Python, path: &str, mode: u32) -> PyResult<()> {
        let path = self._adjust_cwd(path);
        let attr = breezy_transport::sftp::Attributes {
            permissions: Some(mode),
            ..Default::default()
        };
        py.allow_threads(|| self.sftp.setstat(path.as_str(), &attr))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))
    }

    fn setstat(&mut self, py: Python, path: &str, attr: &SFTPAttributes) -> PyResult<()> {
        let path = self._adjust_cwd(path);
        py.allow_threads(|| self.sftp.setstat(path.as_str(), &attr.0))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))
    }

    fn hardlink(&mut self, py: Python, oldpath: &str, newpath: &str) -> PyResult<()> {
        let newpath = self._adjust_cwd(newpath);
        py.allow_threads(|| self.sftp.hardlink(oldpath, newpath.as_str()))
            .map_err(|e| sftp_error_to_py_err(e, Some(newpath.as_str())))
    }

    fn realpath(
        &mut self,
        py: Python,
        path: &str,
        control_byte: Option<u8>,
        compose_path: Option<&str>,
    ) -> PyResult<String> {
        let path = self._adjust_cwd(path);
        py.allow_threads(|| {
            self.sftp
                .realpath(path.as_str(), control_byte, compose_path)
        })
        .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))
    }

    fn symlink(&mut self, py: Python, oldpath: &str, newpath: &str) -> PyResult<()> {
        let newpath = self._adjust_cwd(newpath);
        py.allow_threads(|| self.sftp.symlink(oldpath, newpath.as_str()))
            .map_err(|e| sftp_error_to_py_err(e, Some(newpath.as_str())))
    }

    fn readlink(&mut self, py: Python, path: &str) -> PyResult<String> {
        let path = self._adjust_cwd(path);
        py.allow_threads(|| self.sftp.readlink(path.as_str()))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))
    }

    fn rename(
        &mut self,
        py: Python,
        oldpath: &str,
        newpath: &str,
        flags: Option<u32>,
    ) -> PyResult<()> {
        let newpath = self._adjust_cwd(newpath);
        let oldpath = self._adjust_cwd(oldpath);
        py.allow_threads(|| self.sftp.rename(oldpath.as_str(), newpath.as_str(), flags))
            .map_err(|e| sftp_error_to_py_err(e, Some(newpath.as_str())))
    }

    fn remove(&mut self, py: Python, path: &str) -> PyResult<()> {
        let path = self._adjust_cwd(path);
        py.allow_threads(|| self.sftp.remove(path.as_str()))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))
    }

    fn rmdir(&mut self, py: Python, path: &str) -> PyResult<()> {
        let path = self._adjust_cwd(path);
        py.allow_threads(|| self.sftp.rmdir(path.as_str()))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))
    }

    fn close(&mut self) -> PyResult<()> {
        Ok(())
    }

    fn open(
        &mut self,
        py: Python,
        path: &str,
        flags: u32,
        attr: &SFTPAttributes,
    ) -> PyResult<SFTPFile> {
        let path = self._adjust_cwd(path);
        let h = py
            .allow_threads(|| self.sftp.open(path.as_str(), flags, &attr.0))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))?;
        Ok(SFTPFile {
            sftp: Arc::clone(&self.sftp),
            file: h,
            offset: 0,
        })
    }

    fn file(
        &mut self,
        py: Python,
        path: &str,
        mode: Option<&str>,
        create_mode: Option<u32>,
    ) -> PyResult<SFTPFile> {
        let path = self._adjust_cwd(path);
        let flags;
        let mut offset = 0;
        let mode = mode.unwrap_or("rt");
        match mode {
            "rt" => {
                flags = breezy_transport::sftp::SFTP_FLAG_READ;
            }
            "ab" => {
                flags = breezy_transport::sftp::SFTP_FLAG_WRITE
                    | breezy_transport::sftp::SFTP_FLAG_CREAT
                    | breezy_transport::sftp::SFTP_FLAG_APPEND;
            }
            "wb" => {
                flags = breezy_transport::sftp::SFTP_FLAG_WRITE
                    | breezy_transport::sftp::SFTP_FLAG_CREAT
                    | breezy_transport::sftp::SFTP_FLAG_TRUNC
                    | breezy_transport::sftp::SFTP_FLAG_READ;
            }
            "rb" => {
                flags = breezy_transport::sftp::SFTP_FLAG_READ;
            }
            "r+" | "rb+" | "b+" => {
                flags = breezy_transport::sftp::SFTP_FLAG_READ
                    | breezy_transport::sftp::SFTP_FLAG_WRITE
                    | breezy_transport::sftp::SFTP_FLAG_CREAT;
            }
            "a+" | "ab+" => {
                flags = breezy_transport::sftp::SFTP_FLAG_READ
                    | breezy_transport::sftp::SFTP_FLAG_WRITE
                    | breezy_transport::sftp::SFTP_FLAG_APPEND
                    | breezy_transport::sftp::SFTP_FLAG_CREAT;
            }
            mode => panic!("Unsupported mode: {}", mode),
        }

        let mut attr = breezy_transport::sftp::Attributes::default();
        attr.permissions = create_mode;

        let h = py
            .allow_threads(|| self.sftp.open(path.as_str(), flags, &attr))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))?;

        let mut ret = SFTPFile {
            sftp: Arc::clone(&self.sftp),
            file: h,
            offset,
        };

        if mode.contains('a') {
            ret.seek(py, 0, 2)?;
        }

        Ok(ret)
    }

    fn opendir(&mut self, py: Python, path: &str) -> PyResult<SFTPDir> {
        let path = self._adjust_cwd(path);
        let h = py
            .allow_threads(|| self.sftp.opendir(path.as_str()))
            .map_err(|e| sftp_error_to_py_err(e, Some(path.as_str())))?;
        Ok(SFTPDir(Arc::clone(&self.sftp), h))
    }

    fn listdir(&mut self, py: Python, path: &str) -> PyResult<Vec<String>> {
        let path = self._adjust_cwd(path);
        let mut dir = self.opendir(py, path.as_str())?;
        let mut entries = Vec::new();
        while let Some(extra_entries) = dir.readdir(py)? {
            for (name, _, _) in extra_entries {
                entries.push(name);
            }
        }
        Ok(entries)
    }
}

pub fn _sftp_rs(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<SFTPClient>()?;
    m.add_class::<SFTPAttributes>()?;
    m.add(
        "SSH_FXF_ACCESS_DISPOSITION",
        breezy_transport::sftp::SSH_FXF_ACCESS_DISPOSITION,
    )?;
    m.add(
        "SSH_FXF_CREATE_NEW",
        breezy_transport::sftp::SSH_FXF_CREATE_NEW,
    )?;
    m.add(
        "SSH_FXF_CREATE_TRUNCATE",
        breezy_transport::sftp::SSH_FXF_CREATE_TRUNCATE,
    )?;
    m.add(
        "SSH_FXF_OPEN_EXISTING",
        breezy_transport::sftp::SSH_FXF_OPEN_EXISTING,
    )?;
    m.add(
        "SSH_FXF_OPEN_OR_CREATE",
        breezy_transport::sftp::SSH_FXF_OPEN_OR_CREATE,
    )?;
    m.add(
        "SSH_FXF_TRUNCATE_EXISTING",
        breezy_transport::sftp::SSH_FXF_TRUNCATE_EXISTING,
    )?;
    m.add(
        "SSH_FXF_APPEND_DATA",
        breezy_transport::sftp::SSH_FXF_APPEND_DATA,
    )?;
    m.add(
        "SSH_FXF_APPEND_DATA_ATOMIC",
        breezy_transport::sftp::SSH_FXF_APPEND_DATA_ATOMIC,
    )?;
    m.add(
        "SSH_FXF_TEXT_MODE",
        breezy_transport::sftp::SSH_FXF_TEXT_MODE,
    )?;
    m.add(
        "SSH_FXF_BLOCK_READ",
        breezy_transport::sftp::SSH_FXF_BLOCK_READ,
    )?;
    m.add(
        "SSH_FXF_BLOCK_WRITE",
        breezy_transport::sftp::SSH_FXF_BLOCK_WRITE,
    )?;
    m.add(
        "SSH_FXF_BLOCK_DELETE",
        breezy_transport::sftp::SSH_FXF_BLOCK_DELETE,
    )?;
    m.add(
        "SSH_FXF_BLOCK_ADVISORY",
        breezy_transport::sftp::SSH_FXF_BLOCK_ADVISORY,
    )?;
    m.add("SSH_FXF_NOFOLLOW", breezy_transport::sftp::SSH_FXF_NOFOLLOW)?;
    m.add(
        "SSH_FXF_DELETE_ON_CLOSE",
        breezy_transport::sftp::SSH_FXF_DELETE_ON_CLOSE,
    )?;
    m.add(
        "SSH_FXF_ACCESS_AUDIT_ALARM_INFO",
        breezy_transport::sftp::SSH_FXF_ACCESS_AUDIT_ALARM_INFO,
    )?;
    m.add(
        "SSH_FXF_ACCESS_BACKUP",
        breezy_transport::sftp::SSH_FXF_ACCESS_BACKUP,
    )?;
    m.add(
        "SSH_FXF_BACKUP_STREAM",
        breezy_transport::sftp::SSH_FXF_BACKUP_STREAM,
    )?;
    m.add(
        "SSH_FXF_OVERRIDE_OWNER",
        breezy_transport::sftp::SSH_FXF_OVERRIDE_OWNER,
    )?;

    m.add("ACE4_READ_DATA", breezy_transport::sftp::ACE4_READ_DATA)?;
    m.add(
        "ACE4_LIST_DIRECTORY",
        breezy_transport::sftp::ACE4_LIST_DIRECTORY,
    )?;
    m.add("ACE4_WRITE_DATA", breezy_transport::sftp::ACE4_WRITE_DATA)?;
    m.add("ACE4_ADD_FILE", breezy_transport::sftp::ACE4_ADD_FILE)?;
    m.add("ACE4_APPEND_DATA", breezy_transport::sftp::ACE4_APPEND_DATA)?;
    m.add(
        "ACE4_ADD_SUBDIRECTORY",
        breezy_transport::sftp::ACE4_ADD_SUBDIRECTORY,
    )?;
    m.add(
        "ACE4_READ_NAMED_ATTRS",
        breezy_transport::sftp::ACE4_READ_NAMED_ATTRS,
    )?;
    m.add(
        "ACE4_WRITE_NAMED_ATTRS",
        breezy_transport::sftp::ACE4_WRITE_NAMED_ATTRS,
    )?;
    m.add("ACE4_EXECUTE", breezy_transport::sftp::ACE4_EXECUTE)?;
    m.add(
        "ACE4_DELETE_CHILD",
        breezy_transport::sftp::ACE4_DELETE_CHILD,
    )?;
    m.add(
        "ACE4_READ_ATTRIBUTES",
        breezy_transport::sftp::ACE4_READ_ATTRIBUTES,
    )?;
    m.add(
        "ACE4_WRITE_ATTRIBUTES",
        breezy_transport::sftp::ACE4_WRITE_ATTRIBUTES,
    )?;
    m.add("ACE4_DELETE", breezy_transport::sftp::ACE4_DELETE)?;
    m.add("ACE4_READ_ACL", breezy_transport::sftp::ACE4_READ_ACL)?;
    m.add("ACE4_WRITE_ACL", breezy_transport::sftp::ACE4_WRITE_ACL)?;
    m.add("ACE4_WRITE_OWNER", breezy_transport::sftp::ACE4_WRITE_OWNER)?;
    m.add("ACE4_SYNCHRONIZE", breezy_transport::sftp::ACE4_SYNCHRONIZE)?;

    m.add("SFTP_FLAG_READ", breezy_transport::sftp::SFTP_FLAG_READ)?;
    m.add("SFTP_FLAG_WRITE", breezy_transport::sftp::SFTP_FLAG_WRITE)?;
    m.add("SFTP_FLAG_APPEND", breezy_transport::sftp::SFTP_FLAG_APPEND)?;
    m.add("SFTP_FLAG_CREAT", breezy_transport::sftp::SFTP_FLAG_CREAT)?;
    m.add("SFTP_FLAG_TRUNC", breezy_transport::sftp::SFTP_FLAG_TRUNC)?;
    m.add("SFTP_FLAG_EXCL", breezy_transport::sftp::SFTP_FLAG_EXCL)?;

    m.add("SFTPError", py.get_type::<SFTPError>())?;
    Ok(())
}
