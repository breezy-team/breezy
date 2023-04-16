use std::collections::{HashMap, HashSet};
use std::hash::Hash;

pub trait ParentsProvider<'a, K> {
    fn get_parent_map(&mut self, keys: &HashSet<&K>) -> HashMap<&'a K, &'a [K]>;
}

pub struct StackedParentsProvider<'a, K> {
    parent_providers: Vec<Box<dyn ParentsProvider<'a, K>>>,
}

impl<'a, K> StackedParentsProvider<'a, K> {
    pub fn new(parent_providers: Vec<Box<dyn ParentsProvider<'a, K>>>) -> Self {
        StackedParentsProvider { parent_providers }
    }
}

impl<'a, K: Hash + Eq> ParentsProvider<'a, K> for StackedParentsProvider<'a, K> {
    fn get_parent_map(&mut self, keys: &HashSet<&K>) -> HashMap<&'a K, &'a [K]> {
        let mut found = HashMap::new();
        let mut remaining = keys.clone();

        for parent_provider in self.parent_providers.iter_mut() {
            if remaining.is_empty() {
                break;
            }

            let new_found = parent_provider.get_parent_map(&remaining);
            found.extend(new_found);
            remaining = remaining
                .difference(&found.keys().cloned().collect())
                .cloned()
                .collect();
        }

        found
    }
}
