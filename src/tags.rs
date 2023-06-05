use bazaar::RevisionId;
use std::collections::HashMap;

pub trait Tags {
    fn get_tag_dict(&self) -> HashMap<String, RevisionId>;
}
