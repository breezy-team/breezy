use crate::{
    Error, Lock, LockError, ReadStream, Result, SmartMedium, Stat, Transport, Url, UrlFragment,
    WriteStream,
};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3_filelike::PyBinaryFile;
use std::collections::HashMap;
use std::fs::Permissions;
use std::io::{Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

import_exception!(breezy.errors, TransportError);
import_exception!(breezy.errors, NoSmartMedium);
import_exception!(breezy.errors, InProcessTransport);
import_exception!(breezy.errors, NotLocalUrl);
import_exception!(breezy.transport, NoSuchFile);
import_exception!(breezy.errors, FileExists);
import_exception!(breezy.errors, TransportNotPossible);
import_exception!(breezy.errors, UrlError);
import_exception!(breezy.errors, PermissionDenied);
import_exception!(breezy.errors, PathNotChild);
import_exception!(breezy.errors, ShortReadvError);
import_exception!(breezy.errors, LockContention);
import_exception!(breezy.errors, LockFailed);

struct PySmartMedium(PyObject);

impl SmartMedium for PySmartMedium {}

pub struct PyTransport(PyObject);

impl From<PyObject> for PyTransport {
    fn from(obj: PyObject) -> Self {
        PyTransport(obj)
    }
}

fn map_py_err_to_lock_err(e: PyErr) -> LockError {
    Python::with_gil(|py| {
        if e.is_instance_of::<LockContention>(py) {
            LockError::Contention(e.value(py).getattr("lock").unwrap().extract().unwrap())
        } else if e.is_instance_of::<LockFailed>(py) {
            let v = e.value(py);
            LockError::Failed(
                v.getattr("lock").unwrap().extract().unwrap(),
                v.getattr("why").unwrap().extract().unwrap(),
            )
        } else {
            LockError::IoError(e.into())
        }
    })
}

struct PyLock(PyObject);

impl Lock for PyLock {
    fn unlock(&mut self) -> std::result::Result<(), LockError> {
        Python::with_gil(|py| {
            self.0
                .call_method0(py, "unlock")
                .map_err(map_py_err_to_lock_err)?;
            Ok(())
        })
    }
}

impl<'py> IntoPyObject<'py> for PyTransport {
    type Target = PyAny;

    type Output = Bound<'py, Self::Target>;

    type Error = PyErr;

    fn into_pyobject(self, py: Python<'py>) -> std::result::Result<Self::Output, Self::Error> {
        Ok(self.0.bind(py).clone())
    }
}

impl From<PyErr> for Error {
    fn from(e: PyErr) -> Self {
        Python::with_gil(|py| {
            let arg = |_i| -> Option<String> {
                let args = e.value(py).getattr("args").unwrap();
                match args.get_item(0) {
                    Ok(a) if a.is_none() => None,
                    Ok(a) => Some(a.extract::<String>().unwrap()),
                    Err(_) => None,
                }
            };
            if e.is_instance_of::<InProcessTransport>(py) {
                Error::InProcessTransport
            } else if e.is_instance_of::<NotLocalUrl>(py) {
                Error::NotLocalUrl(arg(0).unwrap())
            } else if e.is_instance_of::<NoSuchFile>(py) {
                Error::NoSuchFile(arg(0))
            } else if e.is_instance_of::<FileExists>(py) {
                Error::FileExists(arg(0))
            } else if e.is_instance_of::<TransportNotPossible>(py) {
                Error::TransportNotPossible
            } else if e.is_instance_of::<PermissionDenied>(py) {
                Error::PermissionDenied(arg(0))
            } else if e.is_instance_of::<PathNotChild>(py) {
                Error::PathNotChild
            } else if e.is_instance_of::<ShortReadvError>(py) {
                let value = e.value(py);
                Error::ShortReadvError(
                    value.getattr("path").unwrap().extract::<String>().unwrap(),
                    value.getattr("offset").unwrap().extract::<u64>().unwrap(),
                    value.getattr("length").unwrap().extract::<u64>().unwrap(),
                    value.getattr("actual").unwrap().extract::<u64>().unwrap(),
                )
            } else {
                panic!("{}", e.to_string())
            }
        })
    }
}

impl ReadStream for PyBinaryFile {}

// Bit of a hack - this reads the entire buffer, and then streams it
fn py_read(r: &mut dyn Read) -> PyResult<PyObject> {
    Python::with_gil(|py| {
        let mut buffer = Vec::new();
        r.read_to_end(&mut buffer)?;
        let io = py.import("io")?;
        let bytesio = io.getattr("BytesIO")?;
        Ok(bytesio.call1((buffer,))?.to_object(py))
    })
}

struct PyWriteStream(PyObject);

impl Write for PyWriteStream {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "write", (buf,))?;
            Ok(obj.extract::<usize>(py)?)
        })
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Python::with_gil(|py| {
            self.0.call_method0(py, "flush")?;
            Ok(())
        })
    }
}

impl WriteStream for PyWriteStream {
    fn sync_data(&self) -> std::io::Result<()> {
        Python::with_gil(|py| {
            self.0.call_method0(py, "fdatasync")?;
            Ok(())
        })
    }
}

impl std::fmt::Debug for PyTransport {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "PyTransport({:?})", self.0)
    }
}

impl Transport for PyTransport {
    fn external_url(&self) -> Result<Url> {
        Python::with_gil(|py| {
            let obj = self.0.call_method0(py, "external_url")?;
            let s = obj.extract::<String>(py)?;
            Url::parse(&s).map_err(Error::from)
        })
    }

    fn get_bytes(&self, path: &str) -> Result<Vec<u8>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "get_bytes", (path,))?;
            let bytes = obj.extract::<Bound<PyBytes>>(py)?;
            Ok(bytes.as_bytes().to_vec())
        })
    }

    fn get(&self, path: &str) -> Result<Box<dyn ReadStream + Send + Sync>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "get", (path,))?;
            Ok(Box::new(PyBinaryFile::from(obj)) as Box<dyn ReadStream + Send + Sync>)
        })
    }

    fn base(&self) -> Url {
        Python::with_gil(|py| {
            let obj = self.0.getattr(py, "base").unwrap();
            let s = obj.extract::<String>(py).unwrap();
            Url::parse(&s).unwrap()
        })
    }

    fn has(&self, path: &UrlFragment) -> Result<bool> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "has", (path,))?;
            Ok(obj.extract::<bool>(py)?)
        })
    }

    fn has_any(&self, paths: &[&UrlFragment]) -> Result<bool> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "has_any", (paths.to_vec(),))?;
            Ok(obj.extract::<bool>(py)?)
        })
    }

    fn mkdir(&self, relpath: &UrlFragment, perms: Option<Permissions>) -> Result<()> {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "mkdir", (relpath, perms.map(|p| p.mode())))?;
            Ok(())
        })
    }

    fn ensure_base(&self, perms: Option<Permissions>) -> Result<bool> {
        Python::with_gil(|py| {
            let obj = self
                .0
                .call_method1(py, "ensure_base", (perms.map(|p| p.mode()),))?;
            Ok(obj.extract::<bool>(py)?)
        })
    }

    fn stat(&self, path: &UrlFragment) -> Result<Stat> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "stat", (path,)).unwrap();
            let stat_result = obj.extract::<PyObject>(py)?;

            let mtime = if let Ok(mtime) = stat_result.getattr(py, "mtime") {
                Some(mtime.extract::<f64>(py)?)
            } else {
                None
            };

            Ok(Stat {
                mode: stat_result.getattr(py, "st_mode")?.extract::<u32>(py)?,
                size: stat_result.getattr(py, "st_size")?.extract::<usize>(py)?,
                mtime,
            })
        })
    }

    fn clone(&self, path: Option<&UrlFragment>) -> Result<Box<dyn Transport>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "clone", (path,))?;
            let transport: Box<dyn Transport> = Box::new(PyTransport(obj));
            Ok(transport)
        })
    }

    fn relpath(&self, path: &Url) -> Result<String> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "relpath", (path.to_string(),))?;
            Ok(obj.extract::<String>(py)?)
        })
    }

    fn abspath(&self, relpath: &UrlFragment) -> Result<Url> {
        let s = Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "abspath", (relpath,))?;
            obj.extract::<String>(py)
        })?;
        Url::parse(&s).map_err(Error::from)
    }

    fn put_file(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn Read,
        mode: Option<Permissions>,
    ) -> Result<u64> {
        let f = py_read(f)?;
        Python::with_gil(|py| {
            let ret = self
                .0
                .call_method1(py, "put_file", (relpath, f, mode.map(|p| p.mode())))?;
            Ok(ret.extract::<u64>(py)?)
        })
    }

    fn put_bytes(
        &self,
        relpath: &UrlFragment,
        bytes: &[u8],
        mode: Option<Permissions>,
    ) -> Result<()> {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "put_bytes", (relpath, bytes, mode.map(|p| p.mode())))?;
            Ok(())
        })
    }

    fn put_file_non_atomic(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn Read,
        mode: Option<Permissions>,
        create_parent: Option<bool>,
        parent_mode: Option<Permissions>,
    ) -> Result<()> {
        let f = py_read(f)?;
        Python::with_gil(|py| {
            self.0.call_method1(
                py,
                "put_file_non_atomic",
                (
                    relpath,
                    f,
                    mode.map(|p| p.mode()),
                    create_parent,
                    parent_mode.map(|p| p.mode()),
                ),
            )?;
            Ok(())
        })
    }

    fn put_bytes_non_atomic(
        &self,
        relpath: &UrlFragment,
        bytes: &[u8],
        mode: Option<Permissions>,
        create_parent: Option<bool>,
        parent_mode: Option<Permissions>,
    ) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(
                py,
                "put_bytes_non_atomic",
                (
                    relpath,
                    bytes,
                    mode.map(|p| p.mode()),
                    create_parent,
                    parent_mode.map(|p| p.mode()),
                ),
            )?;
            Ok(())
        })
    }

    fn delete(&self, relpath: &UrlFragment) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "delete", (relpath,))?;
            Ok(())
        })
    }

    fn rmdir(&self, relpath: &UrlFragment) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "rmdir", (relpath,))?;
            Ok(())
        })
    }

    fn rename(&self, relpath: &UrlFragment, new_relpath: &UrlFragment) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "rename", (relpath, new_relpath))?;
            Ok(())
        })
    }

    fn set_segment_parameter(&mut self, key: &str, value: Option<&str>) -> Result<()> {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "set_segment_parameter", (key, value))?;
            Ok(())
        })
    }

    fn get_segment_parameters(&self) -> Result<HashMap<String, String>> {
        Python::with_gil(|py| {
            Ok(self
                .0
                .call_method0(py, "get_segment_parameters")?
                .extract::<HashMap<String, String>>(py)?)
        })
    }

    fn create_prefix(&self, permissions: Option<Permissions>) -> Result<()> {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "create_prefix", (permissions.map(|p| p.mode()),))?;
            Ok(())
        })
    }

    fn recommended_page_size(&self) -> usize {
        Python::with_gil(|py| {
            self.0
                .getattr(py, "recommended_page_size")
                .unwrap()
                .extract::<usize>(py)
                .unwrap()
        })
    }

    fn is_readonly(&self) -> bool {
        Python::with_gil(|py| {
            self.0
                .getattr(py, "is_readonly")
                .unwrap()
                .extract::<bool>(py)
                .unwrap()
        })
    }

    fn readv(
        &self,
        relpath: &UrlFragment,
        offsets: Vec<(u64, usize)>,
        adjust_for_latency: bool,
        upper_limit: Option<u64>,
    ) -> Box<dyn Iterator<Item = Result<(u64, Vec<u8>)>> + Send> {
        let iter = Python::with_gil(|py| {
            self.0
                .call_method1(
                    py,
                    "readv",
                    (relpath, offsets, adjust_for_latency, upper_limit),
                )?
                .extract::<PyObject>(py)
        });

        if let Err(e) = iter {
            return Box::new(std::iter::once(Err(Error::from(e))));
        }

        Box::new(std::iter::from_fn(move || {
            Python::with_gil(|py| -> Option<Result<(u64, Vec<u8>)>> {
                let iter = iter.as_ref().unwrap();
                match iter.call_method0(py, "__next__") {
                    Ok(obj) => {
                        if obj.is_none(py) {
                            None
                        } else {
                            let (offset, bytes) = obj.extract::<(u64, Vec<u8>)>(py).unwrap();
                            Some(Ok((offset, bytes)))
                        }
                    }
                    Err(e) => Some(Err(Error::from(e))),
                }
            })
        }))
    }

    fn append_bytes(
        &self,
        relpath: &UrlFragment,
        bytes: &[u8],
        permissions: Option<Permissions>,
    ) -> Result<u64> {
        Python::with_gil(|py| {
            let pos = self.0.call_method1(
                py,
                "append_bytes",
                (relpath, bytes, permissions.map(|p| p.mode())),
            )?;
            Ok(pos.extract::<u64>(py)?)
        })
    }

    fn append_file(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn Read,
        permissions: Option<Permissions>,
    ) -> Result<u64> {
        let f = py_read(f)?;
        Python::with_gil(|py| {
            let pos = self.0.call_method1(
                py,
                "append_file",
                (relpath, f, permissions.map(|p| p.mode())),
            )?;
            Ok(pos.extract::<u64>(py)?)
        })
    }

    fn readlink(&self, relpath: &UrlFragment) -> Result<String> {
        Python::with_gil(|py| {
            Ok(self
                .0
                .call_method1(py, "readlink", (relpath,))?
                .extract::<String>(py)?)
        })
    }

    fn hardlink(&self, relpath: &UrlFragment, new_relpath: &UrlFragment) -> Result<()> {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "hardlink", (relpath, new_relpath))?;
            Ok(())
        })
    }

    fn symlink(&self, relpath: &UrlFragment, new_relpath: &UrlFragment) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "symlink", (relpath, new_relpath))?;
            Ok(())
        })
    }

    fn iter_files_recursive(&self) -> Box<dyn Iterator<Item = Result<String>>> {
        let iter = Python::with_gil(|py| {
            self.0
                .call_method0(py, "iter_files_recursive")?
                .extract::<PyObject>(py)
        });

        if let Err(e) = iter {
            return Box::new(std::iter::once(Err(Error::from(e))));
        }

        Box::new(std::iter::from_fn(move || {
            Python::with_gil(|py| -> Option<Result<String>> {
                let iter = iter.as_ref().unwrap();
                match iter.call_method0(py, "__next__") {
                    Ok(obj) => {
                        if obj.is_none(py) {
                            None
                        } else {
                            let path = obj.extract::<String>(py).unwrap();
                            Some(Ok(path))
                        }
                    }
                    Err(e) => Some(Err(Error::from(e))),
                }
            })
        }))
    }

    fn open_write_stream(
        &self,
        relpath: &UrlFragment,
        permissions: Option<Permissions>,
    ) -> Result<Box<dyn WriteStream + Send + Sync>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(
                py,
                "open_write_stream",
                (relpath, permissions.map(|p| p.mode())),
            )?;
            let file = PyWriteStream(obj);
            Ok(Box::new(file) as Box<dyn WriteStream + Send + Sync>)
        })
    }

    fn delete_tree(&self, relpath: &UrlFragment) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "delete_tree", (relpath,))?;
            Ok(())
        })
    }

    fn r#move(&self, src: &UrlFragment, dst: &UrlFragment) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "move", (src, dst))?;
            Ok(())
        })
    }

    fn copy_tree(&self, src: &UrlFragment, dst: &UrlFragment) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "copy_tree", (src, dst))?;
            Ok(())
        })
    }

    fn copy_tree_to_transport(&self, _to_transport: &dyn Transport) -> Result<()> {
        unimplemented!()
    }

    fn copy_to(
        &self,
        _relpaths: &[&UrlFragment],
        _to_transport: &dyn Transport,
        _permissions: Option<Permissions>,
    ) -> Result<usize> {
        unimplemented!()
    }

    fn can_roundtrip_unix_modebits(&self) -> bool {
        Python::with_gil(|py| {
            self.0
                .getattr(py, "can_roundtrip_unix_modebits")
                .unwrap()
                .extract::<bool>(py)
                .unwrap()
        })
    }

    fn local_abspath(&self, relpath: &UrlFragment) -> Result<PathBuf> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "local_abspath", (relpath,))?;
            Ok(obj.extract::<PathBuf>(py)?)
        })
    }

    fn list_dir(&self, relpath: &UrlFragment) -> Box<dyn Iterator<Item = Result<String>>> {
        let iter = Python::with_gil(|py| {
            self.0
                .call_method1(py, "list_dir", (relpath,))?
                .extract::<PyObject>(py)
        });

        if let Err(e) = iter {
            return Box::new(std::iter::once(Err(Error::from(e))));
        }

        Box::new(std::iter::from_fn(move || {
            Python::with_gil(|py| -> Option<Result<String>> {
                let iter = iter.as_ref().unwrap();
                match iter.call_method0(py, "__next__") {
                    Ok(obj) => {
                        if obj.is_none(py) {
                            None
                        } else {
                            Some(obj.extract::<String>(py).map_err(|e| e.into()))
                        }
                    }
                    Err(e) => Some(Err(e.into())),
                }
            })
        }))
    }

    fn listable(&self) -> bool {
        Python::with_gil(|py| {
            self.0
                .call_method0(py, "listable")
                .unwrap()
                .extract::<bool>(py)
                .unwrap()
        })
    }

    fn lock_write(&self, relpath: &UrlFragment) -> Result<Box<dyn Lock + Send + Sync>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "lock_write", (relpath,))?;
            let file: Box<dyn Lock + Send + Sync> = Box::new(PyLock(obj));
            Ok(file)
        })
    }

    fn lock_read(&self, relpath: &UrlFragment) -> Result<Box<dyn Lock + Send + Sync>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "lock_read", (relpath,))?;
            let file: Box<dyn Lock + Send + Sync> = Box::new(PyLock(obj));
            Ok(file)
        })
    }

    fn get_smart_medium(&self) -> Result<Box<dyn SmartMedium>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method0(py, "get_smart_medium").unwrap();
            if obj.is_none(py) {
                return Err(Error::NoSmartMedium);
            }
            let obj = obj.extract::<PyObject>(py).unwrap();
            let medium = PySmartMedium(obj);
            Ok(Box::new(medium) as Box<dyn SmartMedium>)
        })
    }

    fn copy(&self, src: &UrlFragment, dst: &UrlFragment) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "copy", (src, dst))?;
            Ok(())
        })
    }
}
