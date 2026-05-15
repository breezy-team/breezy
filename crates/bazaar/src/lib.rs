#[cfg(feature = "pyo3")]
use pyo3::{prelude::*, types::PyBytes};
use std::fmt::{Debug, Error, Formatter};

#[derive(Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct RevisionId(Vec<u8>);

impl Debug for RevisionId {
    fn fmt(&self, f: &mut Formatter) -> Result<(), Error> {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

impl std::fmt::Display for RevisionId {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

impl From<Vec<u8>> for RevisionId {
    fn from(v: Vec<u8>) -> Self {
        check_valid(&v);
        RevisionId(v)
    }
}

impl From<&[u8]> for RevisionId {
    fn from(v: &[u8]) -> Self {
        check_valid(v);
        RevisionId(v.to_vec())
    }
}

impl From<RevisionId> for Vec<u8> {
    fn from(v: RevisionId) -> Self {
        v.0
    }
}

#[cfg(feature = "pyo3")]
impl FromPyObject<'_, '_> for RevisionId {
    type Error = pyo3::PyErr;

    fn extract(ob: Borrowed<'_, '_, PyAny>) -> PyResult<Self> {
        let s: Vec<u8> = ob.extract()?;
        if !is_valid(&s) {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Invalid revision id: {:?}",
                s
            )));
        }
        Ok(RevisionId::from(s))
    }
}

#[cfg(feature = "pyo3")]
impl<'py> IntoPyObject<'py> for &RevisionId {
    type Target = pyo3::types::PyBytes;

    type Output = Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        let obj = PyBytes::new(py, &self.0);
        Ok(obj)
    }
}

#[cfg(feature = "pyo3")]
impl<'py> IntoPyObject<'py> for RevisionId {
    type Target = pyo3::types::PyBytes;

    type Output = Bound<'py, Self::Target>;

    type Error = pyo3::PyErr;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        (&self).into_pyobject(py)
    }
}

pub const NULL_REVISION: &[u8] = b"null:";
pub const CURRENT_REVISION: &[u8] = b"current:";

pub fn is_valid(id: &[u8]) -> bool {
    if id.contains(&b' ') || id.contains(&b'\t') || id.contains(&b'\n') || id.contains(&b'\r') {
        return false;
    }

    if id.is_empty() {
        return false;
    }

    true
}

pub fn check_valid(id: &[u8]) {
    if !is_valid(id) {
        if let Ok(id) = String::from_utf8(id.to_vec()) {
            panic!("Invalid id: {:?}", id);
        } else {
            panic!("Invalid id: {:?}", id);
        }
    }
}

impl RevisionId {
    pub fn is_null(&self) -> bool {
        self.0 == NULL_REVISION
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }

    pub fn is_reserved(&self) -> bool {
        self.0.ends_with(b":")
    }
}
