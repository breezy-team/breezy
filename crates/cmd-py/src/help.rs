use breezy::help::Section;
use pyo3::prelude::*;

#[pyclass]
struct DynamicHelpTopic(std::sync::Arc<breezy::help::DynamicHelpTopic>);

#[pymethods]
impl DynamicHelpTopic {
    #[pyo3(signature = (additional_see_also = None, plain = None))]
    fn get_help_text(
        &self,
        additional_see_also: Option<Vec<String>>,
        plain: Option<bool>,
    ) -> String {
        let additional_see_also = additional_see_also
            .as_ref()
            .map(|v| v.iter().map(|s| s.as_str()).collect::<Vec<_>>());
        self.0
            .get_help_text(additional_see_also.as_deref(), plain.unwrap_or(true))
    }

    #[getter]
    fn get_summary(&self) -> String {
        self.0.summary.to_string()
    }

    #[getter]
    fn get_name(&self) -> String {
        self.0.name.to_string()
    }

    fn get_contents(&self) -> String {
        self.0.get_contents().to_string()
    }
}

#[pyclass]
struct StaticHelpTopic(&'static breezy::help::HelpTopic);

#[pymethods]
impl StaticHelpTopic {
    fn get_contents(&self) -> String {
        self.0.get_contents().to_string()
    }

    #[getter]
    fn get_summary(&self) -> String {
        self.0.summary.to_string()
    }

    #[getter]
    fn get_name(&self) -> String {
        self.0.name.to_string()
    }

    #[pyo3(signature = (additional_see_also = None, plain = None))]
    fn get_help_text(
        &self,
        additional_see_also: Option<Vec<String>>,
        plain: Option<bool>,
    ) -> String {
        let additional_see_also = additional_see_also
            .as_ref()
            .map(|v| v.iter().map(|s| s.as_str()).collect::<Vec<_>>());
        self.0
            .get_help_text(additional_see_also.as_deref(), plain.unwrap_or(true))
    }
}

#[pyclass]
struct HelpTopicRegistry;

#[pymethods]
impl HelpTopicRegistry {
    #[new]
    fn new() -> Self {
        Self
    }

    #[pyo3(signature = (name, contents, summary, section = None))]
    fn register(
        &mut self,
        py: Python,
        name: &str,
        contents: PyObject,
        summary: &str,
        section: Option<&str>,
    ) -> PyResult<()> {
        let contents = if let Ok(contents) = contents.extract::<String>(py) {
            breezy::help::HelpContents::Closure(Box::new(move |_| contents.clone()))
        } else {
            let f = contents.extract::<PyObject>(py)?;
            let name = name.to_string();
            breezy::help::HelpContents::Closure(Box::new(move |h| {
                Python::with_gil(|py| match f.call1(py, (h,)) {
                    Ok(s) => s.extract::<String>(py).unwrap(),
                    Err(e) => {
                        e.print(py);
                        panic!("error while generating help text for {}", name);
                    }
                })
            }))
        };
        let topic = breezy::help::DynamicHelpTopic {
            name: name.to_string(),
            contents,
            summary: summary.to_string(),
            section: section
                .map(|s| {
                    std::convert::TryInto::try_into(s).map_err(|_| {
                        pyo3::exceptions::PyValueError::new_err("invalid section name")
                    })
                })
                .transpose()?
                .unwrap_or(Section::List),
        };
        breezy::help::register_topic(topic);
        Ok(())
    }

    #[pyo3(signature = (name, module, path, summary, section = None))]
    fn register_lazy(
        &mut self,
        py: Python,
        name: &str,
        module: &str,
        path: &str,
        summary: &str,
        section: Option<&str>,
    ) -> PyResult<()> {
        let mut o = py.import(module)?.into_any();

        for attr in path.split('.') {
            o = o.getattr(attr)?;
        }

        self.register(py, name, o.unbind(), summary, section)
    }

    #[pyo3(signature = (name))]
    fn get<'a>(&self, py: Python<'a>, name: &str) -> PyResult<Option<Bound<'a, PyAny>>> {
        if let Some(topic) = breezy::help::get_dynamic_topic(name) {
            Ok(Some(Bound::new(py, DynamicHelpTopic(topic))?.into_any()))
        } else {
            breezy::help::get_static_topic(name)
                .map(|topic| Ok(Bound::new(py, StaticHelpTopic(topic))?.into_any()))
                .transpose()
        }
    }

    #[pyo3(signature = (name, ))]
    fn get_summary(&self, py: Python, name: &str) -> PyResult<Option<String>> {
        let topic = self.get(py, name)?;

        topic
            .map(|topic| Ok(topic.getattr("summary")?.extract::<String>()?))
            .transpose()
    }

    #[pyo3(signature = (name, ))]
    fn get_detail(&self, py: Python, name: &str) -> PyResult<Option<String>> {
        let topic = self.get(py, name)?;
        topic
            .map(|topic| {
                Ok(topic
                    .getattr("get_contents")?
                    .call0()?
                    .extract::<String>()?)
            })
            .transpose()
    }

    fn __contains__(&self, name: &str) -> bool {
        self.keys().contains(&name.to_string())
    }

    fn keys(&self) -> Vec<String> {
        breezy::help::iter_static_topics()
            .map(|t| t.name.to_string())
            .chain(breezy::help::iter_dynamic_topics().map(|t| t.name.to_string()))
            .collect()
    }

    fn get_topics_for_section(&self, section: &str) -> Vec<String> {
        let section = section
            .try_into()
            .expect("invalid section name passed to get_topics_for_section");
        breezy::help::iter_static_topics()
            .filter(|t| t.section == section)
            .map(|t| t.name.to_string())
            .chain(
                breezy::help::iter_dynamic_topics()
                    .filter(|t| t.section == section)
                    .map(|t| t.name.to_string()),
            )
            .collect()
    }
}

#[pyfunction]
fn _format_see_also(topics: Vec<String>) -> String {
    let topics_ref = topics.iter().map(|t| t.as_str()).collect::<Vec<_>>();
    breezy::help::format_see_also(topics_ref.as_slice())
}

#[pyfunction]
fn known_env_variables() -> Vec<(String, String)> {
    breezy::help::KNOWN_ENV_VARIABLES
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

pub(crate) fn help_topics(m: &Bound<PyModule>) -> PyResult<()> {
    m.add_class::<DynamicHelpTopic>()?;
    m.add_class::<StaticHelpTopic>()?;
    m.add_class::<HelpTopicRegistry>()?;
    m.add_wrapped(wrap_pyfunction!(_format_see_also))?;
    m.add_wrapped(wrap_pyfunction!(known_env_variables))?;
    Ok(())
}
