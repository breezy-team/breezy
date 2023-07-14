pub fn join_segment_parameters(
    url: &url::Url,
    parameters: std::collections::HashMap<String, String>,
) -> url::Url {
    pyo3::Python::with_gil(|py| {
        let urlutils = py.import("breezy.urlutils").unwrap();
        urlutils
            .call_method1("join_segment_parameters", (url.to_string(), parameters))
            .unwrap()
            .extract::<String>()
            .map(|s| url::Url::parse(s.as_str()).unwrap())
            .unwrap()
    })
}

pub fn split_segment_parameters(
    url: &url::Url,
) -> (url::Url, std::collections::HashMap<String, String>) {
    pyo3::Python::with_gil(|py| {
        let urlutils = py.import("breezy.urlutils").unwrap();
        urlutils
            .call_method1("split_segment_parameters", (url.to_string(),))
            .unwrap()
            .extract::<(String, std::collections::HashMap<String, String>)>()
            .map(|(s, m)| (url::Url::parse(s.as_str()).unwrap(), m))
            .unwrap()
    })
}
