use crate::{ParentMap, Parents};
use std::collections::{HashMap, HashSet};
use std::hash::Hash;

pub trait ParentsProvider<K: PartialEq + Eq + Clone + Hash> {
    fn get_parent_map(&self, keys: &HashSet<K>) -> ParentMap<K>;
}

pub struct StackedParentsProvider<K> {
    parent_providers: Vec<Box<dyn ParentsProvider<K>>>,
}

impl<K> StackedParentsProvider<K> {
    pub fn new(parent_providers: Vec<Box<dyn ParentsProvider<K>>>) -> Self {
        StackedParentsProvider { parent_providers }
    }
}

impl<K: Hash + Eq + Clone> ParentsProvider<K> for StackedParentsProvider<K> {
    fn get_parent_map(&self, keys: &HashSet<K>) -> ParentMap<K> {
        let mut found = ParentMap::new();
        let mut remaining = keys.clone();

        for parent_provider in self.parent_providers.iter() {
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

pub struct DictParentsProvider<K: Hash + Eq + Clone>(ParentMap<K>);

impl<K: Hash + Eq + Clone> From<ParentMap<K>> for DictParentsProvider<K> {
    fn from(parent_map: ParentMap<K>) -> Self {
        DictParentsProvider(parent_map)
    }
}

impl<K: Hash + Eq + Clone> From<HashMap<K, Vec<K>>> for DictParentsProvider<K> {
    fn from(parent_map: HashMap<K, Vec<K>>) -> Self {
        DictParentsProvider::new(ParentMap(
            parent_map
                .into_iter()
                .map(|(k, v)| (k, Parents::Known(v)))
                .collect(),
        ))
    }
}

impl<K: Hash + Eq + Clone> DictParentsProvider<K> {
    pub fn new(parent_map: ParentMap<K>) -> Self {
        DictParentsProvider(parent_map)
    }
}

impl<K: Hash + Eq + Clone> ParentsProvider<K> for DictParentsProvider<K> {
    fn get_parent_map(&self, keys: &HashSet<K>) -> ParentMap<K> {
        ParentMap(
            keys.iter()
                .filter_map(|k| self.0.get_key_value(k))
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
        )
    }
}
