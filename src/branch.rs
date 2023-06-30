use crate::tags::Tags;
use bazaar::RevisionId;

pub trait Branch {
    fn last_revision(&self) -> RevisionId;

    fn name(&self) -> String;

    fn tags(&self) -> Box<dyn Tags>;
}
