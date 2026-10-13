use crate::tags::{Error, Tags};
use bazaar::RevisionId;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// A wrapper around a Python tags object.
///
/// This struct provides a Rust interface to Python tags objects, implementing
/// the `Tags` trait. It allows Rust code to interact with Python tag management
/// implementations.
pub struct PyTags(pub(crate) Py<PyAny>);

import_exception!(breezy.errors, NoSuchTag);

impl Tags for PyTags {
    fn get_tag_dict(&self) -> Result<std::collections::HashMap<String, RevisionId>, Error> {
        Python::attach(|py| -> PyResult<_> {
            let dict = self.0.call_method0(py, "get_tag_dict")?;
            let dict = dict.cast_bound::<PyDict>(py)?;
            let mut map = std::collections::HashMap::new();
            for (key, value) in dict.iter() {
                map.insert(key.extract::<String>()?, value.extract::<RevisionId>()?);
            }
            Ok(map)
        })
        .map_err(Error::Python)
    }

    fn delete_tag(&mut self, tag: &str) -> Result<(), Error> {
        Python::attach(|py| {
            self.0.call_method1(py, "delete_tag", (tag,)).map_err(|e| {
                if e.is_instance_of::<NoSuchTag>(py) {
                    Error::NoSuchTag(tag.to_string())
                } else {
                    Error::Python(e)
                }
            })
        })?;
        Ok(())
    }
}
