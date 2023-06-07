use breezy::help::Section;
use pyo3::prelude::*;

#[pyclass]
struct HelpTopic(std::sync::Arc<breezy::help::HelpTopic>);

#[pymethods]
impl HelpTopic {}

#[pyclass]
struct HelpTopicRegistry;

#[pymethods]
impl HelpTopicRegistry {
    #[new]
    fn new() -> Self {
        Self
    }

    fn register(
        &mut self,
        py: Python,
        name: &str,
        contents: PyObject,
        summary: &str,
        section: Option<&str>,
    ) -> PyResult<()> {
        let contents = if let Ok(contents) = contents.extract::<String>(py) {
            breezy::help::HelpContents::Closure(Box::new(|_| contents))
        } else {
            let f = contents.extract::<PyObject>(py)?;
            breezy::help::HelpContents::Closure(Box::new(move |h| {
                Python::with_gil(|py| {
                    let s = f.call1(py, (h,)).unwrap();
                    s.extract::<String>(py).unwrap()
                })
            }))
        };
        let topic = breezy::help::HelpTopic {
            name: name.into(),
            contents,
            summary: summary.into(),
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

    fn get(&self, name: &str) -> Option<HelpTopic> {
        breezy::help::get_topic(name).map(|t| HelpTopic(t))
    }

    fn get_summary(&self, name: &str) -> Option<String> {
        let topic = self.get(name)?;
        Some(topic.0.summary.to_string())
    }

    fn get_detail(&self, name: &str) -> Option<String> {
        let topic = self.get(name)?;
        Some(topic.0.get_contents().to_string())
    }

    fn __contains__(&self, name: &str) -> bool {
        self.keys().contains(&name)
    }

    fn keys(&self) -> Vec<&str> {
        breezy::help::iter_topics().map(|t| t.name).collect()
    }
}

#[pyfunction]
fn _format_see_also(topics: Vec<&str>) -> String {
    breezy::help::format_see_also(topics.as_slice())
}

pub(crate) fn help_topics(m: &PyModule) -> PyResult<()> {
    m.add_class::<HelpTopic>()?;
    m.add_class::<HelpTopicRegistry>()?;
    m.add_wrapped(wrap_pyfunction!(_format_see_also))?;
    Ok(())
}
