use crate::branch::{py_tag_selector, Branch, RegularBranch};
use crate::revisionid::RevisionId;
use pyo3::conversion::ToPyObject;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[derive(Clone)]
pub struct Forge(PyObject);

pub enum MergeProposalStatus {
    All,
    Open,
    Merged,
}

impl ToString for MergeProposalStatus {
    fn to_string(&self) -> String {
        match self {
            MergeProposalStatus::All => "all".to_string(),
            MergeProposalStatus::Open => "open".to_string(),
            MergeProposalStatus::Merged => "merged".to_string(),
        }
    }
}

#[derive(Clone)]
pub struct MergeProposal(PyObject);

impl MergeProposal {
    pub fn new(obj: PyObject) -> Self {
        MergeProposal(obj)
    }

    pub fn reopen(&self) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0.call_method0(py, "reopen")?;
            Ok(())
        })
    }

    pub fn close(&self) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0.call_method0(py, "close")?;
            Ok(())
        })
    }

    pub fn url(&self) -> PyResult<url::Url> {
        Python::with_gil(|py| {
            let url = self.0.getattr(py, "url")?;
            Ok(url.extract::<String>(py)?.parse().unwrap())
        })
    }

    pub fn is_merged(&self) -> PyResult<bool> {
        Python::with_gil(|py| {
            let is_merged = self.0.call_method0(py, "is_merged")?;
            is_merged.extract(py)
        })
    }

    pub fn is_closed(&self) -> PyResult<bool> {
        Python::with_gil(|py| {
            let is_closed = self.0.call_method0(py, "is_closed")?;
            is_closed.extract(py)
        })
    }

    pub fn get_title(&self) -> PyResult<Option<String>> {
        Python::with_gil(|py| {
            let title = self.0.call_method0(py, "get_title")?;
            title.extract(py)
        })
    }

    pub fn set_title(&self, title: Option<&str>) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "set_title", (title,))?;
            Ok(())
        })
    }

    pub fn get_commit_message(&self) -> PyResult<Option<String>> {
        Python::with_gil(|py| {
            let commit_message = self.0.call_method0(py, "get_commit_message")?;
            commit_message.extract(py)
        })
    }

    pub fn set_commit_message(&self, commit_message: Option<&str>) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "set_commit_message", (commit_message,))?;
            Ok(())
        })
    }

    pub fn get_description(&self) -> PyResult<Option<String>> {
        Python::with_gil(|py| {
            let description = self.0.call_method0(py, "get_description")?;
            description.extract(py)
        })
    }

    pub fn set_description(&self, description: Option<&str>) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "set_description", (description,))?;
            Ok(())
        })
    }

    pub fn merge(&self, auto: bool) -> PyResult<()> {
        Python::with_gil(|py| {
            self.0.call_method1(py, "merge", (auto,))?;
            Ok(())
        })
    }
}

#[pyclass]
pub struct ProposalBuilder(PyObject, PyObject);

impl ProposalBuilder {
    pub fn description(self, description: &str) -> Self {
        Python::with_gil(|py| {
            self.1
                .as_ref(py)
                .set_item("description", description)
                .unwrap();
        });
        self
    }

    pub fn labels(self, labels: &[&str]) -> Self {
        Python::with_gil(|py| {
            self.1.as_ref(py).set_item("labels", labels).unwrap();
        });
        self
    }

    pub fn reviewers(self, reviewers: &[&str]) -> Self {
        Python::with_gil(|py| {
            self.1.as_ref(py).set_item("reviewers", reviewers).unwrap();
        });
        self
    }

    pub fn allow_collaboration(self, allow_collaboration: bool) -> Self {
        Python::with_gil(|py| {
            self.1
                .as_ref(py)
                .set_item("allow_collaboration", allow_collaboration)
                .unwrap();
        });
        self
    }

    pub fn title(self, title: &str) -> Self {
        Python::with_gil(|py| {
            self.1.as_ref(py).set_item("title", title).unwrap();
        });
        self
    }

    pub fn commit_message(self, commit_message: &str) -> Self {
        Python::with_gil(|py| {
            self.1
                .as_ref(py)
                .set_item("commit_message", commit_message)
                .unwrap();
        });
        self
    }

    pub fn build(self) -> PyResult<MergeProposal> {
        Python::with_gil(|py| {
            let kwargs = self.1;
            let proposal = self.0.call_method1(py, "create_proposal", (kwargs,))?;
            Ok(MergeProposal::new(proposal))
        })
    }
}

impl Forge {
    pub fn merge_proposal_description_format(&self) -> String {
        Python::with_gil(|py| {
            let merge_proposal_description_format = self
                .to_object(py)
                .getattr(py, "merge_proposal_description_format")
                .unwrap();
            merge_proposal_description_format.extract(py).unwrap()
        })
    }

    pub fn supports_merge_proposal_commit_message(&self) -> bool {
        Python::with_gil(|py| {
            let supports_merge_proposal_commit_message = self
                .to_object(py)
                .getattr(py, "supports_merge_proposal_commit_message")
                .unwrap();
            supports_merge_proposal_commit_message.extract(py).unwrap()
        })
    }

    pub fn supports_merge_proposal_title(&self) -> bool {
        Python::with_gil(|py| {
            let supports_merge_proposal_title = self
                .to_object(py)
                .getattr(py, "supports_merge_proposal_title")
                .unwrap();
            supports_merge_proposal_title.extract(py).unwrap()
        })
    }

    pub fn get_proposer(
        &self,
        from_branch: &dyn Branch,
        to_branch: &dyn Branch,
    ) -> PyResult<ProposalBuilder> {
        Python::with_gil(|py| {
            Ok(ProposalBuilder(
                self.0.call_method1(
                    py,
                    "get_proposer",
                    (from_branch.to_object(py), to_branch.to_object(py)),
                )?,
                PyDict::new(py).into(),
            ))
        })
    }

    pub fn get_derived_branch(
        &self,
        main_branch: &dyn Branch,
        name: &str,
        owner: Option<&str>,
        preferred_schemes: Option<&[&str]>,
    ) -> PyResult<Box<dyn Branch>> {
        Python::with_gil(|py| {
            let kwargs = PyDict::new(py);
            kwargs.set_item("main_branch", main_branch.to_object(py))?;
            kwargs.set_item("name", name)?;
            if let Some(owner) = owner {
                kwargs.set_item("owner", owner)?;
            }
            if let Some(preferred_schemes) = preferred_schemes {
                kwargs.set_item("preferred_schemes", preferred_schemes)?;
            }
            let branch =
                self.to_object(py)
                    .call_method(py, "get_derived_branch", (), Some(kwargs))?;
            Ok(Box::new(RegularBranch::new(branch)) as Box<dyn Branch>)
        })
    }

    pub fn iter_proposals(
        &self,
        source_branch: &dyn Branch,
        target_branch: &dyn Branch,
        status: MergeProposalStatus,
    ) -> PyResult<impl Iterator<Item = MergeProposal>> {
        Python::with_gil(move |py| {
            let kwargs = PyDict::new(py);
            kwargs.set_item("status", status.to_string())?;
            let proposals: Vec<PyObject> = self
                .0
                .call_method(
                    py,
                    "iter_proposals",
                    (&source_branch.to_object(py), &target_branch.to_object(py)),
                    Some(kwargs),
                )?
                .extract(py)?;
            Ok(proposals.into_iter().map(MergeProposal::new))
        })
    }

    pub fn publish_derived(
        &self,
        local_branch: &dyn Branch,
        main_branch: &dyn Branch,
        name: &str,
        overwrite_existing: Option<bool>,
        owner: Option<&str>,
        stop_revision: Option<&RevisionId>,
        tag_selector: Option<Box<dyn Fn(String) -> bool>>,
    ) -> PyResult<(Box<dyn Branch>, url::Url)> {
        Python::with_gil(|py| {
            let kwargs = PyDict::new(py);
            kwargs.set_item("local_branch", &local_branch.to_object(py))?;
            kwargs.set_item("main_branch", &main_branch.to_object(py))?;
            kwargs.set_item("name", name)?;
            if let Some(overwrite_existing) = overwrite_existing {
                kwargs.set_item("overwrite_existing", overwrite_existing)?;
            }
            if let Some(owner) = owner {
                kwargs.set_item("owner", owner)?;
            }
            if let Some(stop_revision) = stop_revision {
                kwargs.set_item("stop_revision", stop_revision)?;
            }
            if let Some(tag_selector) = tag_selector {
                kwargs.set_item("tag_selector", py_tag_selector(py, tag_selector)?)?;
            }
            let (b, u): (PyObject, String) = self
                .to_object(py)
                .call_method(py, "publish_derived", (), Some(kwargs))?
                .extract(py)?;
            Ok((
                Box::new(RegularBranch::new(b)) as Box<dyn Branch>,
                u.parse::<url::Url>().unwrap(),
            ))
        })
    }

    pub fn get_push_url(&self, branch: &dyn Branch) -> url::Url {
        Python::with_gil(|py| {
            let url = self
                .to_object(py)
                .call_method1(py, "get_push_url", (&branch.to_object(py),))
                .unwrap()
                .extract::<String>(py)
                .unwrap();
            url.parse::<url::Url>().unwrap()
        })
    }
}

impl FromPyObject<'_> for Forge {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        Ok(Forge(ob.to_object(ob.py())))
    }
}

impl ToPyObject for Forge {
    fn to_object(&self, py: Python) -> PyObject {
        self.0.to_object(py)
    }
}

pub fn get_forge(branch: &dyn Branch) -> Forge {
    Python::with_gil(|py| {
        let m = py.import("breezy.forge").unwrap();
        let forge = m
            .call_method1("get_forge", (branch.to_object(py),))
            .unwrap();
        Forge(forge.to_object(py))
    })
}

pub fn determine_title(description: &str) -> String {
    Python::with_gil(|py| {
        let m = py.import("breezy.forge").unwrap();
        let title = m.call_method1("determine_title", (description,)).unwrap();
        title.extract::<String>()
    })
    .unwrap()
}