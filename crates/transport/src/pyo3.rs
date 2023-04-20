use pyo3::prelude::*;
use std::fs::Permissions;
use std::os::unix::fs::PermissionsExt;
use crate::{Transport, Error, Result, Url, UrlFragment, Stat};
use std::io::Read;
use pyo3::types::PyBytes;
use pyo3_file::PyFileLikeObject;
use pyo3::import_exception;
use std::collections::HashMap;

import_exception!(breezy.errors, TransportError);
import_exception!(breezy.errors, NoSmartMedium);
import_exception!(breezy.errors, InProcessTransport);
import_exception!(breezy.errors, NotLocalUrl);
import_exception!(breezy.errors, NotLocalTransport);
import_exception!(breezy.errors, NoSuchFile);
import_exception!(breezy.errors, FileExists);
import_exception!(breezy.errors, TransportNotPossible);
import_exception!(breezy.errors, NotImplemented);
import_exception!(breezy.errors, InvalidPath);
import_exception!(breezy.errors, UrlError);
import_exception!(breezy.errors, PermissionDenied);
import_exception!(breezy.errors, PathNotChild);

struct PyTransport(PyObject);

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
                Error::NotLocalUrl
            } else if e.is_instance_of::<NoSuchFile>(py) {
                Error::NoSuchFile
            } else if e.is_instance_of::<FileExists>(py) {
                Error::FileExists
            } else if e.is_instance_of::<TransportNotPossible>(py) {
                Error::TransportNotPossible
            } else if e.is_instance_of::<NotImplemented>(py) {
                Error::NotImplemented
            } else if e.is_instance_of::<InvalidPath>(py) {
                Error::InvalidPath
            } else if e.is_instance_of::<PermissionDenied>(py) {
                Error::PermissionDenied
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

    fn get(&self, path: &str) -> Result<Box<dyn Read>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "get", (path,))?;
            Ok(PyFileLikeObject::with_requirements(obj, true, false, false).map(|f| Box::new(f) as Box<dyn Read>)?)
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

    fn mkdir(&self, relpath: &UrlFragment, perms: Option<Permissions>) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "mkdir", (relpath, perms.map(|p| p.mode())))?;
            Ok(())
        })
    }

    fn ensure_base(&self, perms: Option<Permissions>) -> Result<bool> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "ensure_base", (perms.map(|p| p.mode()), ))?;
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

    fn abspath(&self, relpath: &UrlFragment) -> Result<Url> {
        let s = Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "abspath", (relpath,))?;
            obj.extract::<String>(py)
        })?;
        Ok(Url::parse(&s).map_err(Error::from)?)
    }

    fn put_file(&self, relpath: &UrlFragment, f: &mut dyn Read, mode: Option<Permissions>) -> Result<()> {
        let f = py_read(f)?;
        Python::with_gil(|py| {
            self.0.call_method1(py, "put_file", (relpath, f, mode.map(|p| p.mode())))?;
            Ok(())
        })
    }

    fn put_bytes(&self, relpath: &UrlFragment, bytes: &[u8], mode: Option<Permissions>) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "put_bytes", (relpath, bytes, mode.map(|p| p.mode())))?;
            Ok(())
        })
    }

    fn put_file_non_atomic(&self, relpath: &UrlFragment, f: &mut dyn Read, mode: Option<Permissions>, create_parent: Option<bool>, parent_mode: Option<Permissions>) -> Result<()> {
        let f = py_read(f)?;
        Python::with_gil(|py| {
            self.0.call_method1(py, "put_file_non_atomic", (relpath, f, mode.map(|p| p.mode()), create_parent, parent_mode.map(|p| p.mode())))?;
            Ok(())
        })
    }

    fn put_bytes_non_atomic(&self, relpath: &UrlFragment, bytes: &[u8], mode: Option<Permissions>, create_parent: Option<bool>, parent_mode: Option<Permissions>) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "put_bytes_non_atomic", (relpath, bytes, mode.map(|p| p.mode()), create_parent, parent_mode.map(|p| p.mode())))?;
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
            self.0.call_method1(py, "set_segment_parameter", (key, value))?;
            Ok(())
        })
    }

    fn get_segment_parameters(&self) -> Result<HashMap<String, String>> {
        Python::with_gil(|py| {
            Ok(self.0.call_method0(py, "get_segment_parameters")?.extract::<HashMap<String, String>>(py)?)
        })
    }

    fn create_prefix(&self, permissions: Option<Permissions>) -> Result<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "create_prefix", (permissions.map(|p| p.mode()),))?;
            Ok(())
        })
    }
}
