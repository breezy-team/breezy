use std::collections::{HashMap, HashSet};
use std::hash::Hash;

pub trait ParentsProvider<K> {
    fn get_parent_map<'a>(&'a mut self, keys: &HashSet<&K>) -> HashMap<&'a K, &'a [K]>;
}

pub struct StackedParentsProvider<K> {
    parent_providers: Vec<Box<dyn ParentsProvider<K>>>,
}

impl<K> StackedParentsProvider<K> {
    pub fn new(parent_providers: Vec<Box<dyn ParentsProvider<K>>>) -> Self {
        StackedParentsProvider { parent_providers }
    }
}

impl<K: Hash + Eq> ParentsProvider<K> for StackedParentsProvider<K> {
    fn get_parent_map<'a>(&'a mut self, keys: &HashSet<&K>) -> HashMap<&'a K, &'a [K]> {
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

pub struct DictParentsProvider<K> {
    parent_map: HashMap<K, Vec<K>>,
}

impl<K> DictParentsProvider<K> {
    pub fn new(parent_map: HashMap<K, Vec<K>>) -> Self {
        DictParentsProvider { parent_map }
    }
}

impl<K: Hash + Eq> ParentsProvider<K> for DictParentsProvider<K> {
    fn get_parent_map<'a>(&'a mut self, keys: &HashSet<&K>) -> HashMap<&'a K, &'a [K]> {
        keys.iter()
            .filter_map(|k| {
                self.parent_map
                    .get_key_value(k)
                    .map(|(k, v)| (k, v.as_slice()))
            })
            .collect()
    }
}
