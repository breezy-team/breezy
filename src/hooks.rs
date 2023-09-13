use pyo3::prelude::*;

pub struct HookDict(PyObject);

pub struct Hook(PyObject);

impl HookDict {
    pub fn new(module: &str, cls: &str, name: &str) -> Self {
        Python::with_gil(|py| -> PyResult<HookDict> {
            let module = PyModule::import(py, module)?;
            let cls = module.getattr(cls)?;
            let entrypoint = cls.getattr(name)?;
            Ok(Self(entrypoint.to_object(py)))
        })
        .unwrap()
    }

    pub fn clear(&self, name: &str) -> PyResult<()> {
        Python::with_gil(|py| {
            let entrypoint = self.0.as_ref(py).get_item(name)?;
            entrypoint.call_method0("clear")?;
            Ok(())
        })
    }

    pub fn add(&self, name: &str, func: Hook) -> PyResult<()> {
        Python::with_gil(|py| {
            let entrypoint = self.0.as_ref(py).get_item(name)?;
            entrypoint.call_method1("add", (func.0,))?;
            Ok(())
        })
    }

    pub fn get(&self, name: &str) -> PyResult<Vec<Hook>> {
        Python::with_gil(|py| {
            let entrypoint = self.0.as_ref(py).get_item(name)?;
            Ok(entrypoint
                .extract::<Vec<PyObject>>()?
                .into_iter()
                .map(Hook)
                .collect())
        })
    }
}
