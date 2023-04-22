use crate::{Error, Lock, Result, SmartMedium, Stat, Transport, Url, UrlFragment};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3_file::PyFileLikeObject;
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

struct PySmartMedium(PyObject);

impl SmartMedium for PySmartMedium {}

struct PyTransport(PyObject);

struct PyLock(PyObject);

impl Lock for PyLock {
    fn unlock(&mut self) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method0(py, "unlock")?;
            Ok(())
        })
    }
}

impl IntoPy<PyObject> for PyTransport {
    fn into_py(self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl From<PyErr> for Error {
    fn from(e: PyErr) -> Self {
        Python::with_gil(|py| {
            if e.is_instance_of::<InProcessTransport>(py) {
                Error::InProcessTransport
            } else if e.is_instance_of::<NotLocalUrl>(py) {
                let args = e.value(py).getattr("args").unwrap();
                Error::NotLocalUrl(args.get_item(0).unwrap().extract::<String>().unwrap())
            } else if e.is_instance_of::<NoSuchFile>(py) {
                let args = e.value(py).getattr("args").unwrap();
                Error::NoSuchFile(Some(args.get_item(0).unwrap().extract::<String>().unwrap()))
            } else if e.is_instance_of::<FileExists>(py) {
                let args = e.value(py).getattr("args").unwrap();
                Error::FileExists(Some(args.get_item(0).unwrap().extract::<String>().unwrap()))
            } else if e.is_instance_of::<TransportNotPossible>(py) {
                Error::TransportNotPossible
            } else if e.is_instance_of::<PermissionDenied>(py) {
                let args = e.value(py).getattr("args").unwrap();
                Error::PermissionDenied(Some(
                    args.get_item(0).unwrap().extract::<String>().unwrap(),
                ))
            } else if e.is_instance_of::<PathNotChild>(py) {
                Error::PathNotChild
            } else {
                panic!("{}", e.to_string())
            }
        })
    }
}

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

impl Transport for PyTransport {
    fn external_url(&self) -> Result<Url> {
        Python::with_gil(|py| {
            let obj = self.0.call_method0(py, "external_url")?;
            let s = obj.extract::<String>(py)?;
            Ok(Url::parse(&s).map_err(Error::from)?)
        })
    }

    fn get_bytes(&self, path: &str) -> Result<Vec<u8>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "get_bytes", (path,))?;
            let bytes = obj.extract::<&PyBytes>(py)?;
            Ok(bytes.as_bytes().to_vec())
        })
    }

    fn get(&self, path: &str) -> Result<Box<dyn Read + Send + Sync>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "get", (path,))?;
            Ok(PyFileLikeObject::with_requirements(obj, true, false, false)
                .map(|f| Box::new(f) as Box<dyn Read + Send + Sync>)?)
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
            Ok(Stat {
                mode: stat_result.getattr(py, "st_mode")?.extract::<u32>(py)?,
                size: stat_result.getattr(py, "st_size")?.extract::<usize>(py)?,
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
        Ok(Url::parse(&s).map_err(Error::from)?)
    }

    fn put_file(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn Read,
        mode: Option<Permissions>,
    ) -> Result<()> {
        let f = py_read(f)?;
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "put_file", (relpath, f, mode.map(|p| p.mode())))?;
            Ok(())
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
        offsets: &[(u64, usize)],
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>>>> {
        let iter = Python::with_gil(|py| {
            self.0
                .call_method1(py, "readv", (relpath, offsets.to_vec()))?
                .extract::<PyObject>(py)
        });

        if let Err(e) = iter {
            return Box::new(std::iter::once(Err(Error::from(e))));
        }

        Box::new(std::iter::from_fn(move || {
            Python::with_gil(|py| -> Option<Result<Vec<u8>>> {
                let iter = iter.as_ref().unwrap();
                match iter.call_method0(py, "__next__") {
                    Ok(obj) => {
                        if obj.is_none(py) {
                            return None;
                        } else {
                            let bytes = obj.extract::<Vec<u8>>(py).unwrap();
                            Some(Ok(bytes))
                        }
                    }
                    Err(e) => Some(Err(Error::from(e))),
                }
            })
            .into()
        }))
    }

    fn append_bytes(
        &self,
        relpath: &UrlFragment,
        bytes: &[u8],
        permissions: Option<Permissions>,
    ) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(
                py,
                "append_bytes",
                (relpath, bytes, permissions.map(|p| p.mode())),
            )?;
            Ok(())
        })
    }

    fn append_file(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn Read,
        permissions: Option<Permissions>,
    ) -> Result<()> {
        let f = py_read(f)?;
        Python::with_gil(|py| {
            self.0.call_method1(
                py,
                "append_file",
                (relpath, f, permissions.map(|p| p.mode())),
            )?;
            Ok(())
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
                            return None;
                        } else {
                            let path = obj.extract::<String>(py).unwrap();
                            Some(Ok(path))
                        }
                    }
                    Err(e) => Some(Err(Error::from(e))),
                }
            })
            .into()
        }))
    }

    fn open_write_stream(
        &self,
        relpath: &UrlFragment,
        permissions: Option<Permissions>,
    ) -> Result<Box<dyn Write + Send + Sync>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(
                py,
                "open_write_stream",
                (relpath, permissions.map(|p| p.mode())),
            )?;
            let file = PyFileLikeObject::with_requirements(obj, false, true, false).unwrap();
            Ok(Box::new(file) as Box<dyn Write + Send + Sync>)
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

    fn copy_tree_to_transport(&self, to_transport: &dyn Transport) -> Result<()> {
        unimplemented!()
    }

    fn copy_to(
        &self,
        relpaths: &[&str],
        to_transport: &dyn Transport,
        permissions: Option<Permissions>,
    ) -> Result<()> {
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
                            return None;
                        } else {
                            return Some(obj.extract::<String>(py).map_err(|e| e.into()));
                        }
                    }
                    Err(e) => Some(Err(e.into())),
                }
            })
            .into()
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
}
