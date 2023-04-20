use pyo3::prelude::*;
use std::any::Any;
use pyo3::exceptions::{PyValueError, PyException};
use pyo3::types::{PyBytes, PyList};
use url::Url;
use std::fs::Permissions;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use breezy_transport::{Result, UrlFragment};
use pyo3_file::PyFileLikeObject;
use pyo3::create_exception;

create_exception!(_transport_rs, TransportError, PyException);
create_exception!(_transport_rs, InProcessTransport, TransportError);
create_exception!(_transport_rs, NotLocalUrl, TransportError);
create_exception!(_transport_rs, NotLocalTransport, TransportError);
create_exception!(_transport_rs, NoSmartMedium, TransportError);
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

fn map_transport_err_to_py_err(e: breezy_transport::Error) -> PyErr {
    match e {
        breezy_transport::Error::InProcessTransport => InProcessTransport::new_err(()),
        breezy_transport::Error::NotLocalUrl => NotLocalUrl::new_err(()),
        breezy_transport::Error::NoSmartMedium => NoSmartMedium::new_err(()),
        breezy_transport::Error::NoSuchFile => NoSuchFile::new_err(()),
        breezy_transport::Error::FileExists => FileExists::new_err(()),
        breezy_transport::Error::TransportNotPossible => TransportNotPossible::new_err(()),
        breezy_transport::Error::NotImplemented => NotImplemented::new_err(()),
        breezy_transport::Error::InvalidPath => InvalidPath::new_err(()),
        breezy_transport::Error::UrlError(e) => UrlError::new_err(e.to_string()),
        breezy_transport::Error::PermissionDenied => PermissionDenied::new_err(()),
        breezy_transport::Error::PathNotChild => PathNotChild::new_err(()),
        breezy_transport::Error::Io(e) => e.into(),
    }
}

#[cfg(unix)]
fn perms_from_py_object(obj: PyObject) -> Permissions {
    Python::with_gil(|py| {
        let mode = obj.extract::<u32>(py).unwrap();
        Permissions::from_mode(mode)
    })
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

    fn mkdir(&self, path: &str, perms: Option<PyObject>) -> PyResult<()> {
        self.transport.mkdir(path, perms.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn ensure_base(&self, perms: Option<PyObject>) -> PyResult<bool> {
        Ok(self.transport.ensure_base(perms.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)?)
    }

    fn local_abspath(&self, path: &str) -> PyResult<PathBuf> {
        let transport = &self.transport as &dyn Any;
        let local_transport = transport.downcast_ref::<&dyn breezy_transport::LocalTransport>()
            .ok_or_else(|| NotLocalTransport::new_err(()))?;
        local_transport.local_abspath(path).map_err(map_transport_err_to_py_err)
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

struct PyTransport {
    obj: PyObject
}

impl breezy_transport::Transport for PyTransport {
    fn external_url(&self) -> Result<Url> {
        Python::with_gil(|py| {
            let obj = self.obj.call_method0(py, "external_url").unwrap();
            let s = obj.extract::<String>(py).unwrap();
            Ok(Url::parse(&s).unwrap())
        })
    }

    fn get_bytes(&self, path: &str) -> Result<Vec<u8>> {
        Python::with_gil(|py| {
            let obj = self.obj.call_method1(py, "get_bytes", (path,)).unwrap();
            let bytes = obj.extract::<&PyBytes>(py).unwrap();
            Ok(bytes.as_bytes().to_vec())
        })
    }

    fn get(&self, path: &str) -> Result<Box<dyn std::io::Read>> {
        Python::with_gil(|py| {
            let obj = self.obj.call_method1(py, "get", (path,)).unwrap();
            Ok(PyFileLikeObject::with_requirements(obj, true, false, false).map(|f| Box::new(f) as Box<dyn std::io::Read>).unwrap())
        })
    }

    fn base(&self) -> Url {
        Python::with_gil(|py| {
            let obj = self.obj.getattr(py, "base").unwrap();
            let s = obj.extract::<String>(py).unwrap();
            Url::parse(&s).unwrap()
        })
    }

    fn has(&self, path: &UrlFragment) -> Result<bool> {
        Python::with_gil(|py| {
            let obj = self.obj.call_method1(py, "has", (path,)).unwrap();
            Ok(obj.extract::<bool>(py).unwrap())
        })
    }

    fn mkdir(&self, relpath: &UrlFragment, perms: Option<Permissions>) -> Result<()> {
        Python::with_gil(|py| {
            let obj = self.obj.call_method1(py, "mkdir", (relpath, perms.map(|p| p.mode()))).unwrap();
            Ok(())
        })
    }

    fn ensure_base(&self, perms: Option<Permissions>) -> Result<bool> {
        Python::with_gil(|py| {
            let obj = self.obj.call_method1(py, "ensure_base", (perms.map(|p| p.mode()), )).unwrap();
            Ok(obj.extract::<bool>(py).unwrap())
        })
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
