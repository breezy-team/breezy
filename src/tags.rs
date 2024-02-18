use bazaar::RevisionId;
use std::collections::HashMap;
use std::collections::HashSet;

#[derive(Debug)]
pub enum Error {
    NoSuchTag(String),
    TagAlreadyExists(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::NoSuchTag(tag) => write!(f, "No such tag: {}", tag),
            Error::TagAlreadyExists(tag) => write!(f, "Tag already exists: {}", tag),
        }
    }
}

impl std::error::Error for Error {}

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
