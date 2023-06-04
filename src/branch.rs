use bazaar::RevisionId;
pub trait Branch {
    fn last_revision(&self) -> RevisionId;
}
