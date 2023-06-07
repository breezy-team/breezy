use bazaar::RevisionId;

pub trait Tree {
    /// Whether this tree supports rename tracking.
    ///
    /// This defaults to True, but some implementations may want to override
    /// it.
    fn supports_rename_tracking(&self) -> bool;
}

pub trait MutableTree: Tree {
    /// Version file_list, optionally recursing into directories.
    ///
    /// This is designed more towards DWIM for humans than API clarity.
    /// For the specific behaviour see the help for cmd_add().
    ///
    /// :param file_list: List of zero or more paths.  *NB: these are
    ///     interpreted relative to the process cwd, not relative to the
    ///     tree.*  (Add and most other tree methods use tree-relative
    ///     paths.)
    /// :param action: A reporter to be called with the working tree, parent_ie,
    ///     path and kind of the path being added. It may return a file_id if
    ///     a specific one should be used.
    /// :param save: Save the changes after completing the adds. If False
    ///     this provides dry-run functionality by doing the add and not saving
    ///     the changes.
    /// :return: A tuple - files_added, ignored_files. files_added is the count
    ///     of added files, and ignored_files is a dict mapping files that were
    ///     ignored to the rule that caused them to be ignored.
    fn smart_add(
        &mut self,
        file_list: Vec<&str>,
        recurse: Option<bool>,
        save: Option<bool>,
    ) -> (Vec<String>, Vec<String>);

    fn commit(&mut self, message: Option<&str>) -> RevisionId;
}

pub trait RevisionTree: Tree {
    fn get_revision_id(&self) -> RevisionId;
}

pub trait WorkingTree: MutableTree {
    fn abspath(&self, path: &str) -> std::path::PathBuf;

    fn last_revision(&self) -> RevisionId;
}
