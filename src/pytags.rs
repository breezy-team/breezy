use crate::tags::{Error, Tags};
use bazaar::RevisionId;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub struct PyTags(pub(crate) PyObject);

import_exception!(breezy.errors, NoSuchTag);

impl Tags for PyTags {
    fn get_tag_dict(&self) -> std::collections::HashMap<String, RevisionId> {
        Python::with_gil(|py| {
            let dict = self.0.call_method0(py, "get_tag_dict").unwrap();
            let dict = dict.downcast_bound::<PyDict>(py).unwrap();
            let mut map = std::collections::HashMap::new();
            for (key, value) in dict.iter() {
                let key = key.extract::<String>().unwrap();
                let value = value.extract::<Vec<u8>>().unwrap();
                map.insert(key, RevisionId::from(value));
            }
            map
        })
    }

    fn delete_tag(&mut self, tag: &str) -> Result<(), Error> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "delete_tag", (tag,)).map_err(|e| {
                if e.is_instance_of::<NoSuchTag>(py) {
                    Error::NoSuchTag(tag.to_string())
                } else {
                    panic!("unexpected exception: {:?}", e);
                }
            })
        })?;
        Ok(())
    }
}
