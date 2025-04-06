use bazaar::filters::ContentFilter;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::fs::Permissions;
use std::io::Error;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

#[pyclass]
struct HashCache {
    hashcache: Box<bazaar::hashcache::HashCache>,
}

pub struct PyContentFilter {
    content_filter: PyObject,
}

#[pyclass]
struct PyChunkIterator {
    input: Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send>,
}

#[pymethods]
impl PyChunkIterator {
    fn __next__(&mut self, py: Python) -> PyResult<Option<PyObject>> {
        match self.input.next() {
            Some(Ok(item)) => Ok(Some(PyBytes::new_bound(py, &item).to_object(py))),
            Some(Err(e)) => Err(e.into()),
            None => Ok(None),
        }
    }
}

fn map_py_err_to_io_err(e: PyErr) -> Error {
    Error::new(std::io::ErrorKind::Other, e.to_string())
}

fn map_py_err_to_iter_io_err(e: PyErr) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send> {
    Box::new(std::iter::once(Err(map_py_err_to_io_err(e))))
}

impl PyContentFilter {
    fn _impl(
        &self,
        input: Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send>,
        worker: &str,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send> {
        Python::with_gil(|py| {
            let worker = self.content_filter.getattr(py, worker);
            let py_input = PyChunkIterator { input };
            let py_output = worker.unwrap().call1(py, (py_input,));
            if let Err(e) = py_output {
                return map_py_err_to_iter_io_err(e);
            }
            let py_output = py_output.unwrap();
            let next = move || {
                Python::with_gil(|py| {
                    let item = py_output.call_method0(py, "__next__");
                    match item {
                        Err(e) => Some(Err(map_py_err_to_io_err(e))),
                        Ok(item) => {
                            if item.is_none(py) {
                                None
                            } else {
                                Some(Ok(item.extract(py).map_err(map_py_err_to_io_err).unwrap()))
                            }
                        }
                    }
                })
            };
            Box::new(std::iter::from_fn(next))
        })
    }
}

impl ContentFilter for PyContentFilter {
    fn reader(
        &self,
        input: Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send>,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send> {
        self._impl(input, "reader")
    }

    fn writer(
        &self,
        input: Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send>,
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>, Error>> + Send> {
        self._impl(input, "worker")
    }
}

fn content_filter_to_fn(
    content_filter_provider: PyObject,
) -> Box<dyn Fn(&Path, u64) -> Box<dyn ContentFilter> + Send> {
    Box::new(move |path, ctime| {
        Python::with_gil(|py| {
            let content_filter_provider = content_filter_provider.to_object(py);
            Box::new(PyContentFilter {
                content_filter: content_filter_provider
                    .call1(py, (path, ctime))
                    .unwrap()
                    .to_object(py),
            })
        })
    })
}

fn extract_fs_time(obj: &Bound<PyAny>) -> Result<i64, PyErr> {
    if let Ok(val) = obj.extract::<i64>() {
        Ok(val)
    } else if let Ok(val) = obj.extract::<f64>() {
        Ok(val as i64)
    } else {
        Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(
            "Expected int or float",
        ))
    }
}

#[pymethods]
impl HashCache {
    #[new]
    fn new(
        root: &str,
        cache_file_name: &str,
        mode: Option<u32>,
        content_filter_provider: Option<PyObject>,
    ) -> Self {
        Self {
            hashcache: Box::new(bazaar::hashcache::HashCache::new(
                Path::new(root),
                Path::new(cache_file_name),
                mode.map(Permissions::from_mode),
                content_filter_provider.map(content_filter_to_fn),
            )),
        }
    }

    fn cache_file_name(&self) -> &str {
        self.hashcache.cache_file_name().to_str().unwrap()
    }

    fn clear(&mut self) {
        self.hashcache.clear();
    }

    fn scan(&mut self) {
        self.hashcache.scan();
    }

    fn get_sha1<'a>(
        &mut self,
        py: Python<'a>,
        path: &str,
        stat_value: Option<Bound<PyAny>>,
    ) -> PyResult<Bound<'a, PyAny>> {
        let sha1;
        if let Some(stat_value) = stat_value {
            let fp = bazaar::hashcache::Fingerprint {
                size: stat_value.getattr("st_size")?.extract()?,
                mtime: extract_fs_time(&stat_value.getattr("st_mtime")?)?,
                ctime: extract_fs_time(&stat_value.getattr("st_ctime")?)?,
                ino: stat_value.getattr("st_ino")?.extract()?,
                dev: stat_value.getattr("st_dev")?.extract()?,
                mode: stat_value.getattr("st_mode")?.extract()?,
            };
            sha1 = self
                .hashcache
                .get_sha1_by_fingerprint(Path::new(path), &fp)?;
        } else {
            let ret = self.hashcache.get_sha1(Path::new(path), None)?;
            if let Some(s) = ret {
                sha1 = s;
            } else {
                return Ok(py.None().into_bound(py));
            }
        }
        Ok(PyBytes::new_bound(py, sha1.as_bytes()).into_any())
    }

    fn write(&mut self) -> PyResult<()> {
        self.hashcache.write().map_err(|e| e.into())
    }

    fn read(&mut self) -> PyResult<()> {
        self.hashcache.read().map_err(|e| e.into())
    }

    fn cutoff_time(&self) -> i64 {
        self.hashcache.cutoff_time()
    }

    fn set_cutoff_offset(&mut self, offset: i64) {
        self.hashcache.set_cutoff_offset(offset);
    }

    #[getter]
    fn miss_count(&self) -> u32 {
        self.hashcache.miss_count()
    }

    #[getter]
    fn hit_count(&self) -> u32 {
        self.hashcache.hit_count()
    }

    #[getter]
    fn needs_write(&self) -> bool {
        self.hashcache.needs_write()
    }

    fn fingerprint(&self, abspath: &str) -> Option<(u64, i64, i64, u64, u64, u32)> {
        let fp = self.hashcache.fingerprint(Path::new(abspath), None);
        fp.map(|fp| (fp.size, fp.mtime, fp.ctime, fp.ino, fp.dev, fp.mode))
    }
}

pub(crate) fn hashcache(m: &Bound<PyModule>) -> PyResult<()> {
    m.add_class::<HashCache>()?;
    Ok(())
}
