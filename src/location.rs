use pyo3::prelude::*;
use url::Url;

pub fn cvs_to_url(cvsroot: &str) -> Url {
    Python::with_gil(|py| {
        let breezy_location = py.import("breezy.location").unwrap();

        breezy_location
            .call_method1("cvs_to_url", (cvsroot,))
            .unwrap()
            .extract::<String>()
            .unwrap()
            .parse()
            .unwrap()
    })
}
