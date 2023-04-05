use pyo3::prelude::*;

use bazaar_hashcache::HashCache;

#[pyclass]
struct HashCacheWrapper {
    hashcache: HashCache,
}

#[pymethods]
impl HashCacheWrapper {
    #[new]
    fn new() -> Self {
        Self {
            hashcache: HashCache::new(),
        }
    }
}

#[pymodule]
fn _hashcache_rs(_: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<HashCacheWrapper>()?;
    Ok(())
}
