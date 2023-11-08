//! TreeBuilder helper class.
//!
//! TreeBuilders are used to build trees of various shapes or properties. This
//! can be extremely useful in testing for instance.

use crate::tree::{Error, MutableTree};

/// A TreeBuilder allows the creation of specific content in one tree at a time.
pub struct TreeBuilder<T: MutableTree> {
    tree: Option<T>,
    root_done: bool,
}

impl<T: MutableTree> TreeBuilder<T> {
    pub fn new() -> TreeBuilder<T> {
        TreeBuilder {
            tree: None,
            root_done: false,
        }
    }

    pub fn start_tree(&mut self, mut tree: T) {
        if self.tree.is_some() {
            panic!("TreeBuilder already has a tree");
        }
        tree.lock_tree_write().expect("lock_tree_write");
        self.tree = Some(tree);
        self.root_done = false;
    }

    pub fn finish_tree(&mut self) -> T {
        let mut tree = if let Some(tree) = self.tree.take() {
            tree
        } else {
            panic!("TreeBuilder does not have a tree");
        };
        tree.unlock().expect("unlock");
        tree
    }

    /// Build recipe into the current tree.
    ///
    /// Args:
    ///   recipe: A sequence of paths. For each path, the corresponding
    ///     path in the current tree is created and added. If the path ends in
    ///     '/' then a directory is added, otherwise a regular file is added.
    pub fn build(&mut self, recipe: &[&str]) -> Result<(), Error> {
        let tree = if let Some(tree) = self.tree.as_mut() {
            tree
        } else {
            panic!("TreeBuilder does not have a tree");
        };
        if !self.root_done {
            tree.add(&[""])?;
            self.root_done = true;
        }
        for name in recipe {
            if name.ends_with('/') {
                tree.mkdir(name.trim_end_matches('/'))?;
            } else {
                let content = format!("contents of {}\n", name);
                tree.put_file_bytes_non_atomic(name, content.as_bytes())?;
                tree.add(&[name])?;
            }
        }
        Ok(())
    }
}

impl<T: MutableTree> Default for TreeBuilder<T> {
    fn default() -> Self {
        Self::new()
    }
}
