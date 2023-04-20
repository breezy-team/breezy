use pyo3::prelude::*;
use std::any::Any;
use pyo3::exceptions::{PyValueError, PyException};
use pyo3::types::{PyBytes, PyList};
use url::Url;
use std::fs::{Metadata, Permissions};
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use breezy_transport::{Result, Stat, Error, UrlFragment};
use pyo3_file::PyFileLikeObject;
use pyo3::create_exception;
use pyo3::import_exception;

import_exception!(breezy.error, TransportError);
import_exception!(breezy.errors, NoSmartMedium);

create_exception!(_transport_rs, InProcessTransport, TransportError);
create_exception!(_transport_rs, NotLocalUrl, TransportError);
create_exception!(_transport_rs, NotLocalTransport, TransportError);
create_exception!(_transport_rs, NoSuchFile, TransportError);
create_exception!(_transport_rs, FileExists, TransportError);
create_exception!(_transport_rs, TransportNotPossible, TransportError);
create_exception!(_transport_rs, NotImplemented, TransportError);
create_exception!(_transport_rs, InvalidPath, TransportError);
create_exception!(_transport_rs, UrlError, TransportError);
create_exception!(_transport_rs, PermissionDenied, TransportError);
create_exception!(_transport_rs, PathNotChild, TransportError);

#[pyclass(subclass)]
struct Transport {
    transport: Box<dyn breezy_transport::Transport>
}

fn map_transport_err_to_py_err(e: Error) -> PyErr {
    match e {
        Error::InProcessTransport => InProcessTransport::new_err(()),
        Error::NotLocalUrl => NotLocalUrl::new_err(()),
        Error::NoSmartMedium => NoSmartMedium::new_err(()),
        Error::NoSuchFile => NoSuchFile::new_err(()),
        Error::FileExists => FileExists::new_err(()),
        Error::TransportNotPossible => TransportNotPossible::new_err(()),
        Error::NotImplemented => NotImplemented::new_err(()),
        Error::InvalidPath => InvalidPath::new_err(()),
        Error::UrlError(e) => UrlError::new_err(e.to_string()),
        Error::PermissionDenied => PermissionDenied::new_err(()),
        Error::PathNotChild => PathNotChild::new_err(()),
        Error::Io(e) => e.into(),
    }
}

fn map_py_err_to_transport_err(e: PyErr) -> Error {
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
    st_size: usize
}

#[pymethods]
impl Transport {
    fn external_url(&self) -> PyResult<String> {
        Ok(self.transport.external_url().map_err(map_transport_err_to_py_err)?.to_string())
    }

    fn get_bytes(&self, py: Python, path: &str) -> PyResult<PyObject> {
        let ret = self.transport.get_bytes(path).map_err(map_transport_err_to_py_err)?;
        Ok(PyBytes::new(py, &ret).to_object(py).to_object(py))
    }

    #[getter]
    fn base(&self) -> PyResult<String> {
        Ok(self.transport.base().to_string())
    }

    fn has(&self, path: &str) -> PyResult<bool> {
        Ok(self.transport.has(path).map_err(map_transport_err_to_py_err)?)
    }

    fn mkdir(&self, path: &str, mode: Option<PyObject>) -> PyResult<()> {
        self.transport.mkdir(path, mode.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn ensure_base(&self, mode: Option<PyObject>) -> PyResult<bool> {
        Ok(self.transport.ensure_base(mode.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)?)
    }

    fn local_abspath(&self, py: Python, path: &str) -> PyResult<PathBuf> {
        let transport = &self.transport as &dyn Any;
        let local_transport = transport.downcast_ref::<&dyn breezy_transport::LocalTransport>()
            .ok_or_else(|| NotLocalTransport::new_err(()))?;
        local_transport.local_abspath(path).map_err(map_transport_err_to_py_err)
    }

    fn get_smart_medium(slf: PyRef<Self>, py: Python) -> PyResult<PyObject> {
        let transport = &slf.transport as &dyn Any;
        if let Some(smart_transport) = transport.downcast_ref::<&dyn breezy_transport::SmartTransport>() {
            Ok(().to_object(py))
        } else {
            Err(NoSmartMedium::new_err((slf.into_py(py), )))
        }
    }

    fn stat(&self, py: Python, path: &str) -> PyResult<PyObject> {
        let stat = self.transport.stat(path).map_err(map_transport_err_to_py_err)?;
        Ok(PyStat { st_size: stat.size, st_mode: stat.mode }.into_py(py))
    }

    fn clone(&self, py: Python, offset: Option<PyObject>) -> PyResult<Self> {
        let inner = if let Some(offset) = offset {
            let offset = offset.extract::<&str>(py)?;
            self.transport.clone(Some(offset))
        } else {
            self.transport.clone(None)
        }.map_err(map_transport_err_to_py_err)?;
        Ok(Transport { transport: inner })
    }
}

#[pyclass(extends=Transport)]
struct LocalTransport {}

#[pymethods]
impl LocalTransport {
    #[new]
    fn new(url: &str) -> PyResult<(Self, Transport)> {
        let url = Url::parse(url)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        Ok((LocalTransport {}, Transport {
            transport: Box::new(breezy_transport::local::FileSystemTransport::from(url))
        }))
    }
}

struct PyTransport(PyObject);

impl IntoPy<PyObject> for PyTransport {
    fn into_py(self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl breezy_transport::Transport for PyTransport {
    fn external_url(&self) -> Result<Url> {
        Python::with_gil(|py| {
            let obj = self.0.call_method0(py, "external_url")
                .map_err(|e| map_py_err_to_transport_err(e))?;
            let s = obj.extract::<String>(py)
                .map_err(|e| map_py_err_to_transport_err(e))?;
            Ok(Url::parse(&s).map_err(Error::from)?)
        })
    }

    fn get_bytes(&self, path: &str) -> Result<Vec<u8>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "get_bytes", (path,))?;
            let bytes = obj.extract::<&PyBytes>(py)?;
            Ok(bytes.as_bytes().to_vec())
        }).map_err(|e| map_py_err_to_transport_err(e))
    }

    fn get(&self, path: &str) -> Result<Box<dyn std::io::Read>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "get", (path,))?;
            Ok(PyFileLikeObject::with_requirements(obj, true, false, false).map(|f| Box::new(f) as Box<dyn std::io::Read>)?)
        }).map_err(|e| map_py_err_to_transport_err(e))
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
        }).map_err(|e| map_py_err_to_transport_err(e))
    }

    fn mkdir(&self, relpath: &UrlFragment, perms: Option<Permissions>) -> Result<()> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "mkdir", (relpath, perms.map(|p| p.mode())))?;
            Ok(())
        }).map_err(|e| map_py_err_to_transport_err(e))
    }

    fn ensure_base(&self, perms: Option<Permissions>) -> Result<bool> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "ensure_base", (perms.map(|p| p.mode()), ))?;
            Ok(obj.extract::<bool>(py)?)
        }).map_err(|e| map_py_err_to_transport_err(e))
    }

    fn stat(&self, path: &UrlFragment) -> Result<Stat> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "stat", (path,)).unwrap();
            let stat_result = obj.extract::<PyObject>(py)?;
            Ok(Stat {
                mode: stat_result.getattr(py, "st_mode")?.extract::<u32>(py)?,
                size: stat_result.getattr(py, "st_size")?.extract::<usize>(py)?,
            })
        }).map_err(map_py_err_to_transport_err)
    }

    fn clone(&self, path: Option<&UrlFragment>) -> Result<Box<dyn breezy_transport::Transport>> {
        Python::with_gil(|py| {
            let obj = self.0.call_method1(py, "clone", (path,))?;
            let t: Box<dyn breezy_transport::Transport> = Box::new(PyTransport(obj));
            Ok(t)
        }).map_err(|e| map_py_err_to_transport_err(e))
    }
}

#[pyfunction]
fn get_test_permutations(py: Python) -> PyResult<PyObject> {
    let test_server_module = py.import("breezy.tests.test_server")?.to_object(py);
    let local_url_server = test_server_module.getattr(py, "LocalURLServer")?;
    let local_transport = py.import("breezy.transport.local")?.getattr("LocalTransport")?;
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
