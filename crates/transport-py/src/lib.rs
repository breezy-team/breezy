use breezy_transport::{Error, Result, Stat, UrlFragment};
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyList};
use pyo3_file::PyFileLikeObject;
use std::any::Any;
use std::collections::HashMap;
use std::fs::{Metadata, Permissions};
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
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

create_exception!(_transport_rs, UrlError, TransportError);

#[pyclass(subclass)]
struct Transport(Box<dyn breezy_transport::Transport>);

fn map_transport_err_to_py_err(e: Error) -> PyErr {
    match e {
        Error::InProcessTransport => InProcessTransport::new_err(()),
        Error::NotLocalUrl(url) => NotLocalUrl::new_err((url,)),
        Error::NoSmartMedium => NoSmartMedium::new_err(()),
        Error::NoSuchFile(name) => NoSuchFile::new_err((name,)),
        Error::FileExists(name) => FileExists::new_err((name,)),
        Error::TransportNotPossible => TransportNotPossible::new_err(()),
        Error::UrlError(e) => UrlError::new_err(e.to_string()),
        Error::PermissionDenied(name) => PermissionDenied::new_err((name,)),
        Error::PathNotChild => PathNotChild::new_err(()),
        Error::UrlutilsError(e) => UrlError::new_err(format!("{:?}", e)),
        Error::Io(e) => e.into(),
        Error::UnexpectedEof => PyValueError::new_err("Unexpected EOF"),
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
    st_size: usize,
}

#[pyclass]
struct PyRead(Box<dyn std::io::Read + Sync + Send>);

#[pyclass]
struct PyWrite(Box<dyn std::io::Write + Sync + Send>);

#[pymethods]
impl PyWrite {
    fn write(&mut self, py: Python, data: &PyBytes) -> PyResult<usize> {
        self.0.write(data.as_bytes()).map_err(|e| e.into())
    }

    fn close(&mut self) -> PyResult<()> {
        Ok(())
    }
}

#[pymethods]
impl PyRead {
    fn read(&mut self, py: Python, size: Option<usize>) -> PyResult<PyObject> {
        let mut buf = vec![0; size.unwrap_or(4096)];
        let ret = self.0.read(&mut buf)?;
        Ok(PyBytes::new(py, &buf[..ret]).to_object(py).to_object(py))
    }

    fn close(&mut self) -> PyResult<()> {
        Ok(())
    }
}

#[pymethods]
impl Transport {
    fn external_url(&self) -> PyResult<String> {
        Ok(self
            .0
            .external_url()
            .map_err(map_transport_err_to_py_err)?
            .to_string())
    }

    fn get_bytes(&self, py: Python, path: &str) -> PyResult<PyObject> {
        let ret = self
            .0
            .get_bytes(path)
            .map_err(map_transport_err_to_py_err)?;
        Ok(PyBytes::new(py, &ret).to_object(py).to_object(py))
    }

    #[getter]
    fn base(&self) -> PyResult<String> {
        Ok(self.0.base().to_string())
    }

    fn has(&self, path: &str) -> PyResult<bool> {
        Ok(self.0.has(path).map_err(map_transport_err_to_py_err)?)
    }

    fn has_any(&self, paths: Vec<&str>) -> PyResult<bool> {
        Ok(self
            .0
            .has_any(paths.as_slice())
            .map_err(map_transport_err_to_py_err)?)
    }

    fn mkdir(&self, path: &str, mode: Option<PyObject>) -> PyResult<()> {
        self.0
            .mkdir(path, mode.map(perms_from_py_object))
            .map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn ensure_base(&self, mode: Option<PyObject>) -> PyResult<bool> {
        Ok(self
            .0
            .ensure_base(mode.map(perms_from_py_object))
            .map_err(map_transport_err_to_py_err)?)
    }

    fn local_abspath(&self, py: Python, path: &str) -> PyResult<PathBuf> {
        let any = &self.0 as &dyn Any;
        if let Some(local_transport) = any.downcast_ref::<&dyn breezy_transport::LocalTransport>() {
            Ok(local_transport
                .local_abspath(path)
                .map_err(map_transport_err_to_py_err)?)
        } else {
            Err(NotLocalUrl::new_err((self.0.base().to_string(),)))
        }
    }

    fn get(&self, py: Python, path: &str) -> PyResult<PyObject> {
        let ret = self.0.get(path).map_err(map_transport_err_to_py_err)?;
        Ok(PyRead(ret).into_py(py))
    }

    fn get_smart_medium(slf: PyRef<Self>, py: Python) -> PyResult<PyObject> {
        let transport = &slf.0 as &dyn Any;
        if let Some(smart_transport) =
            transport.downcast_ref::<&dyn breezy_transport::SmartTransport>()
        {
            Ok(().to_object(py))
        } else {
            Err(NoSmartMedium::new_err((slf.into_py(py),)))
        }
    }

    fn stat(&self, py: Python, path: &str) -> PyResult<PyObject> {
        let stat = self.0.stat(path).map_err(map_transport_err_to_py_err)?;
        Ok(PyStat {
            st_size: stat.size,
            st_mode: stat.mode,
        }
        .into_py(py))
    }

    fn clone(&self, py: Python, offset: Option<PyObject>) -> PyResult<Self> {
        let inner = if let Some(offset) = offset {
            let offset = offset.extract::<&str>(py)?;
            self.0.clone(Some(offset))
        } else {
            self.0.clone(None)
        }
        .map_err(map_transport_err_to_py_err)?;
        Ok(Transport(inner))
    }

    fn relpath(&self, path: &str) -> PyResult<String> {
        let url = Url::parse(path).map_err(|_| PyValueError::new_err((path.to_string(),)))?;
        Ok(self.0.relpath(&url).map_err(map_transport_err_to_py_err)?)
    }

    fn abspath(&self, path: &str) -> PyResult<String> {
        Ok(self
            .0
            .abspath(path)
            .map_err(map_transport_err_to_py_err)?
            .to_string())
    }

    fn put_bytes(&self, path: &str, data: &[u8], mode: Option<PyObject>) -> PyResult<()> {
        self.0
            .put_bytes(path, data, mode.map(perms_from_py_object))
            .map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn put_bytes_non_atomic(
        &self,
        path: &str,
        data: &[u8],
        mode: Option<PyObject>,
        create_parent_dir: Option<bool>,
        dir_permissions: Option<PyObject>,
    ) -> PyResult<()> {
        self.0
            .put_bytes_non_atomic(
                path,
                data,
                mode.map(perms_from_py_object),
                create_parent_dir,
                dir_permissions.map(perms_from_py_object),
            )
            .map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn put_file(&self, path: &str, file: PyObject, mode: Option<PyObject>) -> PyResult<()> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        self.0
            .put_file(path, &mut file, mode.map(perms_from_py_object))
            .map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn put_file_non_atomic(
        &self,
        path: &str,
        file: PyObject,
        mode: Option<PyObject>,
        create_parent_dir: Option<bool>,
        dir_permissions: Option<PyObject>,
    ) -> PyResult<()> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        self.0
            .put_file_non_atomic(
                path,
                &mut file,
                mode.map(perms_from_py_object),
                create_parent_dir,
                dir_permissions.map(perms_from_py_object),
            )
            .map_err(map_transport_err_to_py_err)?;
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
        self.0
            .rename(from, to)
            .map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn set_segment_parameter(&mut self, name: &str, value: Option<&str>) -> PyResult<()> {
        self.0
            .set_segment_parameter(name, value)
            .map_err(map_transport_err_to_py_err)?;
        Ok(())
    }

    fn get_segment_parameters(&self) -> PyResult<HashMap<String, String>> {
        Ok(self
            .0
            .get_segment_parameters()
            .map_err(map_transport_err_to_py_err)?)
    }

    fn create_prefix(&self, mode: Option<PyObject>) -> PyResult<()> {
        self.0
            .create_prefix(mode.map(perms_from_py_object))
            .map_err(map_transport_err_to_py_err)
    }

    fn lock_write(&self, path: &str) -> PyResult<Lock> {
        let transport = &self.0 as &dyn Any;
        let lockable_transport = transport
            .downcast_ref::<&dyn breezy_transport::LockableTransport>()
            .ok_or_else(|| TransportNotPossible::new_err(()))?;

        lockable_transport
            .lock_write(path)
            .map_err(map_transport_err_to_py_err)
            .map(Lock::from)
    }

    fn lock_read(&self, path: &str) -> PyResult<Lock> {
        let transport = &self.0 as &dyn Any;
        let lockable_transport = transport
            .downcast_ref::<&dyn breezy_transport::LockableTransport>()
            .ok_or_else(|| TransportNotPossible::new_err(()))?;

        lockable_transport
            .lock_read(path)
            .map_err(map_transport_err_to_py_err)
            .map(Lock::from)
    }

    fn is_read_locked(&self, path: &str) -> PyResult<bool> {
        let transport = &self.0 as &dyn Any;
        let lockable_transport = transport
            .downcast_ref::<&dyn breezy_transport::LockableTransport>()
            .ok_or_else(|| TransportNotPossible::new_err(()))?;

        Ok(lockable_transport
            .is_read_locked(path)
            .map_err(map_transport_err_to_py_err)?)
    }

    fn recommended_page_size(&self) -> usize {
        self.0.recommended_page_size()
    }

    fn is_readonly(&self) -> bool {
        self.0.is_readonly()
    }

    fn readv(&self, py: Python, path: &str, offsets: Vec<(u64, usize)>) -> PyResult<Vec<PyObject>> {
        self.0
            .readv(path, offsets.as_slice())
            .map(|r| {
                r.map(|o| PyBytes::new(py, &o).to_object(py))
                    .map_err(map_transport_err_to_py_err)
            })
            .collect()
    }

    fn listable(&self) -> bool {
        let transport = &self.0 as &dyn Any;
        transport.is::<&dyn breezy_transport::ListableTransport>()
    }

    fn list_dir(&self, path: &str) -> PyResult<Vec<String>> {
        let transport = &self.0 as &dyn Any;
        let listable_transport = transport
            .downcast_ref::<&dyn breezy_transport::ListableTransport>()
            .ok_or_else(|| TransportNotPossible::new_err(()))?;

        listable_transport
            .list_dir(path)
            .map(|r| r.map_err(map_transport_err_to_py_err))
            .collect::<PyResult<Vec<_>>>()
    }

    fn append_bytes(&self, path: &str, bytes: &[u8], mode: Option<PyObject>) -> PyResult<()> {
        self.0
            .append_bytes(path, bytes, mode.map(perms_from_py_object))
            .map_err(map_transport_err_to_py_err)
    }

    fn append_file(&self, path: &str, file: PyObject, mode: Option<PyObject>) -> PyResult<()> {
        let mut file = PyFileLikeObject::with_requirements(file, true, false, false)?;
        self.0
            .append_file(path, &mut file, mode.map(perms_from_py_object))
            .map_err(map_transport_err_to_py_err)
    }

    fn iter_files_recursive(&self, py: Python) -> PyResult<PyObject> {
        let iter = self.0.iter_files_recursive().map(|r| {
            r.map_err(map_transport_err_to_py_err)
                .map(|o| o.to_object(py))
        });
        iter.collect::<PyResult<Vec<_>>>().map(|v| v.to_object(py))
    }

    fn open_write_stream(&self, path: &str, mode: Option<PyObject>) -> PyResult<PyWrite> {
        self.0
            .open_write_stream(path, mode.map(perms_from_py_object))
            .map_err(map_transport_err_to_py_err)
            .map(|w| PyWrite(w))
    }

    fn delete_tree(&self, path: &str) -> PyResult<()> {
        self.0
            .delete_tree(path)
            .map_err(map_transport_err_to_py_err)
    }

    fn move_(&self, from: &str, to: &str) -> PyResult<()> {
        self.0.move_(from, to).map_err(map_transport_err_to_py_err)
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
        let url = Url::parse(url).map_err(|e| PyValueError::new_err(e.to_string()))?;
        Ok((
            LocalTransport {},
            Transport(Box::new(
                breezy_transport::local::FileSystemTransport::from(url),
            )),
        ))
    }
}

#[pyfunction]
fn get_test_permutations(py: Python) -> PyResult<PyObject> {
    let test_server_module = py.import("breezy.tests.test_server")?.to_object(py);
    let local_url_server = test_server_module.getattr(py, "LocalURLServer")?;
    let local_transport = py
        .import("breezy.transport.local")?
        .getattr("LocalTransport")?;
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
