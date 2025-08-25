#![allow(non_snake_case)]
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyclass]
struct ZLibEstimator {
    estimator: breezy_zlib_util::estimator::ZLibEstimator,
}

#[pymethods]
impl ZLibEstimator {
    #[new]
    fn new(target_size: usize) -> Self {
        ZLibEstimator {
            estimator: breezy_zlib_util::estimator::ZLibEstimator::new(target_size),
        }
    }

    #[getter]
    fn _compressed_size_added(&self) -> PyResult<usize> {
        Ok(self.estimator.compressed_size_added())
    }

    #[getter]
    fn _uncompressed_size_added(&self) -> PyResult<usize> {
        Ok(self.estimator.uncompressed_size_added())
    }

    fn add_content(&mut self, content: &[u8]) -> PyResult<()> {
        self.estimator
            .add_content(content)
            .map_err(|e| PyValueError::new_err(format!("Failed to add content: {}", e)))
    }

    fn full(&mut self) -> PyResult<bool> {
        self.estimator
            .full()
            .map_err(|e| PyValueError::new_err(format!("Failed to check if full: {}", e)))
    }
}

#[pymodule]
fn zlib_util(_py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    m.add_class::<ZLibEstimator>()?;

    Ok(())
}
