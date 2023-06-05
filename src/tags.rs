use bazaar::RevisionId;

pub trait Tags {
    fn get_tag_dict(&self) -> HashMap<String, RevisionId>;
}
