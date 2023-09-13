use pyo3::prelude::*;

pub struct TreeTransform(PyObject);

#[derive(Clone)]
pub struct TreeChange {}

impl From<PyObject> for TreeChange {
    fn from(_ob: PyObject) -> Self {
        TreeChange {}
    }
}

impl FromPyObject<'_> for TreeChange {
    fn extract(_ob: &PyAny) -> PyResult<Self> {
        Ok(TreeChange {})
    }
}

#[derive(Clone)]
pub struct Conflict(PyObject);

impl TreeTransform {
    pub fn iter_changes(&self) -> PyResult<Box<dyn Iterator<Item = TreeChange>>> {
        let mut v: Vec<TreeChange> = vec![];

        Python::with_gil(|py| {
            let ret = self.to_object(py).call_method0(py, "iter_changes")?;

            for item in ret.as_ref(py).iter()? {
                v.push(item?.extract()?);
            }

            Ok(Box::new(v.into_iter()) as Box<dyn Iterator<Item = TreeChange>>)
        })
    }

    pub fn cooked_conflicts(&self) -> PyResult<Vec<Conflict>> {
        let mut v: Vec<Conflict> = vec![];

        Python::with_gil(|py| {
            let ret = self.to_object(py).getattr(py, "cooked_conflicts")?;

            for item in ret.as_ref(py).iter()? {
                v.push(Conflict(item?.into()));
            }

            Ok(v)
        })
    }
}

impl From<PyObject> for TreeTransform {
    fn from(ob: PyObject) -> Self {
        TreeTransform(ob)
    }
}

impl ToPyObject for TreeTransform {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

impl FromPyObject<'_> for TreeTransform {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        Ok(TreeTransform(ob.into()))
    }
}
