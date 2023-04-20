use pyo3::prelude::*;
use std::any::Any;
use pyo3::exceptions::{PyValueError, PyException};
use pyo3::types::{PyBytes, PyList};
use url::Url;
use std::fs::{Metadata, Permissions};
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::collections::HashMap;
use breezy_transport::{Result, Stat, Error, UrlFragment};
use pyo3_file::PyFileLikeObject;
use pyo3::create_exception;
use pyo3::import_exception;

import_exception!(breezy.errors, TransportError);
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
struct Transport(Box<dyn breezy_transport::Transport>);

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
        Error::UrlutilsError(e) => UrlError::new_err(format!("{:?}", e)),
        Error::Io(e) => e.into(),
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
    st_size: usize
}

#[pymethods]
impl Transport {
    fn external_url(&self) -> PyResult<String> {
        Ok(self.0.external_url().map_err(map_transport_err_to_py_err)?.to_string())
    }

    fn get_bytes(&self, py: Python, path: &str) -> PyResult<PyObject> {
        let ret = self.0.get_bytes(path).map_err(map_transport_err_to_py_err)?;
        Ok(PyBytes::new(py, &ret).to_object(py).to_object(py))
    }

    #[getter]
    fn base(&self) -> PyResult<String> {
        Ok(self.0.base().to_string())
    }

    fn has(&self, path: &str) -> PyResult<bool> {
        Ok(self.0.has(path).map_err(map_transport_err_to_py_err)?)
    }

    fn mkdir(&self, path: &str, mode: Option<PyObject>) -> PyResult<()> {
        self.0.mkdir(path, mode.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn ensure_base(&self, mode: Option<PyObject>) -> PyResult<bool> {
        Ok(self.0.ensure_base(mode.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)?)
    }

    fn local_abspath(&self, py: Python, path: &str) -> PyResult<PathBuf> {
        let transport = &self.0 as &dyn Any;
        let local_transport = transport.downcast_ref::<&dyn breezy_transport::LocalTransport>()
            .ok_or_else(|| NotLocalTransport::new_err(()))?;
        local_transport.local_abspath(path).map_err(map_transport_err_to_py_err)
    }

    fn get_smart_medium(slf: PyRef<Self>, py: Python) -> PyResult<PyObject> {
        let transport = &slf.0 as &dyn Any;
        if let Some(smart_transport) = transport.downcast_ref::<&dyn breezy_transport::SmartTransport>() {
            Ok(().to_object(py))
        } else {
            Err(NoSmartMedium::new_err((slf.into_py(py), )))
        }
    }

    fn stat(&self, py: Python, path: &str) -> PyResult<PyObject> {
        let stat = self.0.stat(path).map_err(map_transport_err_to_py_err)?;
        Ok(PyStat { st_size: stat.size, st_mode: stat.mode }.into_py(py))
    }

    fn clone(&self, py: Python, offset: Option<PyObject>) -> PyResult<Self> {
        let inner = if let Some(offset) = offset {
            let offset = offset.extract::<&str>(py)?;
            self.0.clone(Some(offset))
        } else {
            self.0.clone(None)
        }.map_err(map_transport_err_to_py_err)?;
        Ok(Transport(inner))
    }

    fn abspath(&self, path: &str) -> PyResult<String> {
        Ok(self.0.abspath(path).map_err(map_transport_err_to_py_err)?.to_string())
    }

    fn put_bytes(&self, path: &str, data: &[u8], mode: Option<PyObject>) -> PyResult<()> {
        self.0.put_bytes(path, data, mode.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn put_bytes_non_atomic(&self, path: &str, data: &[u8], mode: Option<PyObject>, create_parent_dir: Option<bool>, dir_permissions: Option<PyObject>) -> PyResult<()> {
        self.0.put_bytes_non_atomic(path, data, mode.map(perms_from_py_object), create_parent_dir, dir_permissions.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn put_file(&self, path: &str, file: PyObject, mode: Option<PyObject>) -> PyResult<()> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        self.0.put_file(path, &mut file, mode.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn put_file_non_atomic(&self, path: &str, file: PyObject, mode: Option<PyObject>, create_parent_dir: Option<bool>, dir_permissions: Option<PyObject>) -> PyResult<()> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        self.0.put_file_non_atomic(path, &mut file, mode.map(perms_from_py_object), create_parent_dir, dir_permissions.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn delete(&self, path: &str) -> PyResult<()> {
        self.0.delete(path).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn rmdir(&self, path: &str) -> PyResult<()> {
        self.0.rmdir(path).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn rename(&self, from: &str, to: &str) -> PyResult<()> {
        self.0.rename(from, to).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn set_segment_parameter(&mut self, name: &str, value: Option<&str>) -> PyResult<()> {
        self.0.set_segment_parameter(name, value).map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn get_segment_parameters(&self) -> PyResult<HashMap<String, String>> {
        Ok(self.0.get_segment_parameters().map_err(map_transport_err_to_py_err)?)
    }

    fn create_prefix(&self, mode: Option<PyObject>) -> PyResult<()> {
        self.0.create_prefix(mode.map(perms_from_py_object)).map_err(map_transport_err_to_py_err)
    }

    fn lock_write(&self, path: &str) -> PyResult<Lock> {
        let transport = &self.0 as &dyn Any;
        let lockable_transport = transport.downcast_ref::<&dyn breezy_transport::LockableTransport>()
            .ok_or_else(|| TransportNotPossible::new_err(()))?;

        lockable_transport.lock_write(path).map_err(map_transport_err_to_py_err).map(Lock::from)
    }

    fn lock_read(&self, path: &str) -> PyResult<Lock> {
        let transport = &self.0 as &dyn Any;
        let lockable_transport = transport.downcast_ref::<&dyn breezy_transport::LockableTransport>()
            .ok_or_else(|| TransportNotPossible::new_err(()))?;

        lockable_transport.lock_read(path).map_err(map_transport_err_to_py_err).map(Lock::from)
    }

    fn is_read_locked(&self, path: &str) -> PyResult<bool> {
        let transport = &self.0 as &dyn Any;
        let lockable_transport = transport.downcast_ref::<&dyn breezy_transport::LockableTransport>()
            .ok_or_else(|| TransportNotPossible::new_err(()))?;

        Ok(lockable_transport.is_read_locked(path).map_err(map_transport_err_to_py_err)?)
    }
}

#[pyclass]
struct Lock(Box<dyn breezy_transport::Lock + Send + Sync>);

impl From<Box<dyn breezy_transport::Lock + Send + Sync>> for Lock {
    fn from(lock: Box<dyn breezy_transport::Lock + Send + Sync>) -> Self {
        Lock(lock)
    }
}

#[pymethods]
impl Lock {
    fn unlock(&mut self) -> PyResult<()> {
        self.0.unlock().map_err(map_transport_err_to_py_err)
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
        Ok((LocalTransport {}, Transport(
            Box::new(breezy_transport::local::FileSystemTransport::from(url))
        )))
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
