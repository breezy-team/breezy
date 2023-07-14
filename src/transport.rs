use pyo3::prelude::*;
use pyo3::types::PyDict;

pub struct Transport(pub(crate) PyObject);

impl Transport {
    pub fn new(obj: PyObject) -> Self {
        Transport(obj)
    }
}

impl From<Transport> for PyObject {
    fn from(t: Transport) -> Self {
        t.0
    }
}

pub fn get_transport(url: &url::Url, possible_transports: Option<Vec<Transport>>) -> Transport {
    pyo3::Python::with_gil(|py| {
        let urlutils = py.import("breezy.transport").unwrap();
        let kwargs = PyDict::new(py);
        kwargs
            .set_item(
                "possible_transports",
                possible_transports.map(|t| t.into_iter().map(|t| t.0).collect::<Vec<PyObject>>()),
            )
            .unwrap();
        let o = urlutils
            .call_method("get_transport", (url.to_string(),), Some(kwargs))
            .unwrap();
        Transport(o.to_object(py))
    })
}
