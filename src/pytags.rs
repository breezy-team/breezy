use crate::tags::Tags;
use bazaar::RevisionId;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub struct PyTags(pub(crate) PyObject);

impl Tags for PyTags {
    fn get_tag_dict(&self) -> std::collections::HashMap<String, RevisionId> {
        Python::with_gil(|py| {
            let dict = self.0.call_method0(py, "get_tag_dict").unwrap();
            let dict = dict.downcast::<PyDict>(py).unwrap();
            let mut map = std::collections::HashMap::new();
            for (key, value) in dict.iter() {
                let key = key.extract::<String>().unwrap();
                let value = value.extract::<Vec<u8>>().unwrap();
                map.insert(key, RevisionId::from(value));
            }
            map
        })
    }
}
