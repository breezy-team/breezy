use pyo3::prelude::*;
use std::fs::Permissions;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use pyo3::types::PyBytes;

#[pyclass]
struct HashCache {
    hashcache: Box<bazaar_hashcache::HashCache>,
}

#[pymethods]
impl HashCache {
    #[new]
    fn new(root: &str, cache_file_name: &str, mode: Option<u32>) -> Self {
        Self {
            hashcache: Box::new(bazaar_hashcache::HashCache::new(Path::new(root), Path::new(cache_file_name), mode.map(Permissions::from_mode), None))
        }
    }

    fn cache_file_name(&self) -> String {
        self.hashcache.cache_file_name().to_str().unwrap().to_string()
    }

    fn clear(&mut self) {
        self.hashcache.clear();
    }

    fn scan(&mut self) {
        self.hashcache.scan();
    }

    fn get_sha1(&mut self, py: Python, path: &str, stat_value: Option<&PyAny>) -> PyResult<PyObject> {
        let sha1;
        if let Some(stat_value) = stat_value {
            let fp = bazaar_hashcache::Fingerprint {
                size: stat_value.getattr("st_size")?.extract()?,
                mtime: stat_value.getattr("st_mtime")?.extract()?,
                ctime: stat_value.getattr("st_ctime")?.extract()?,
                ino: stat_value.getattr("st_ino")?.extract()?,
                dev: stat_value.getattr("st_dev")?.extract()?,
                mode: stat_value.getattr("st_mode")?.extract()?,
            };
            sha1 = self.hashcache.get_sha1_by_fingerprint(Path::new(path), &fp)?;
        } else {
            let ret = self.hashcache.get_sha1(Path::new(path), None)?;
            if let Some(s) = ret {
                sha1 = s;
            } else {
                return Ok(py.None());
            }
        }
        Ok(PyBytes::new(py, sha1.as_bytes()).to_object(py))
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

    #[getter]
    fn miss_count(&self) -> u32 {
        self.hashcache.miss_count()
    }

    #[getter]
    fn hit_count(&self) -> u32 {
        self.hashcache.hit_count()
    }

    fn fingerprint(&self, abspath: &str) -> Option<(u64, i64, i64, u64, u64, u32)> {
        let fp = self.hashcache.fingerprint(Path::new(abspath), None);
        fp.map(|fp| (fp.size, fp.mtime, fp.ctime, fp.ino, fp.dev, fp.mode))
    }
}

#[pymodule]
fn hashcache(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<HashCache>()?;
    Ok(())
}
