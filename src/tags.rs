use bazaar::RevisionId;
use std::collections::HashMap;
use std::collections::HashSet;

pub enum Error {
    NoSuchTag(String),
    TagAlreadyExists(String),
}

pub trait Tags {
    fn get_tag_dict(&self) -> HashMap<String, RevisionId>;

    fn get_reverse_tag_dict(&self) -> HashMap<RevisionId, HashSet<String>> {
        let mut reverse_tag_dict = HashMap::new();
        for (tag, rev_id) in self.get_tag_dict() {
            reverse_tag_dict
                .entry(rev_id)
                .or_insert_with(HashSet::new)
                .insert(tag);
        }
        reverse_tag_dict
    }

    fn delete_tag(&mut self, tag: &str) -> Result<(), Error>;
}
