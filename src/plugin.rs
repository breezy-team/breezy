use pyo3::prelude::*;

pub fn load_plugins() {
    pyo3::prepare_freethreaded_python();
    Python::with_gil(|py| {
        let m = py.import("breezy.plugin").unwrap();
        let load_plugins = m.getattr("load_plugins").unwrap();
        load_plugins.call0().unwrap();
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_load_plugins() {
        load_plugins();
    }
}
