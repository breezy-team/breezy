use crate::tree::TreeChange;
use pyo3::prelude::*;

/// Describes changes from one tree to another.
///
/// Contains seven lists with TreeChange objects.
///
/// added
/// removed
/// renamed
/// copied
/// kind_changed
/// modified
/// unchanged
/// unversioned
///
/// Each id is listed only once.
///
/// Files that are both modified and renamed or copied are listed only in
/// renamed or copied, with the text_modified flag true. The text_modified
/// applies either to the content of the file or the target of the
/// symbolic link, depending of the kind of file.
///
/// Files are only considered renamed if their name has changed or
/// their parent directory has changed.  Renaming a directory
/// does not count as renaming all its contents.
///
/// The lists are normally sorted when the delta is created.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TreeDelta {
    pub added: Vec<TreeChange>,
    pub removed: Vec<TreeChange>,
    pub renamed: Vec<TreeChange>,
    pub copied: Vec<TreeChange>,
    pub kind_changed: Vec<TreeChange>,
    pub modified: Vec<TreeChange>,
    pub unchanged: Vec<TreeChange>,
    pub unversioned: Vec<TreeChange>,
    pub missing: Vec<TreeChange>,
}

impl TreeDelta {
    pub fn has_changed(&self) -> bool {
        !self.added.is_empty()
            || !self.removed.is_empty()
            || !self.renamed.is_empty()
            || !self.copied.is_empty()
            || !self.kind_changed.is_empty()
            || !self.modified.is_empty()
    }
}
impl FromPyObject<'_> for TreeDelta {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        let added = ob.getattr("added")?.extract()?;
        let removed = ob.getattr("removed")?.extract()?;
        let renamed = ob.getattr("renamed")?.extract()?;
        let copied = ob.getattr("copied")?.extract()?;
        let kind_changed = ob.getattr("kind_changed")?.extract()?;
        let modified = ob.getattr("modified")?.extract()?;
        let unchanged = ob.getattr("unchanged")?.extract()?;
        let unversioned = ob.getattr("unversioned")?.extract()?;
        let missing = ob.getattr("missing")?.extract()?;
        Ok(TreeDelta {
            added,
            removed,
            renamed,
            copied,
            kind_changed,
            modified,
            unchanged,
            unversioned,
            missing,
        })
    }
}
