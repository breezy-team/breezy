use crate::branch::Branch;
use crate::graphshim::Graph;
use bazaar::RevisionId;

/// Remove tags on revisions between old_tip and new_tip.
///
/// # Arguments
/// branch: Branch to remove tags from
/// graph: Graph object for branch repository
/// old_tip: Old branch tip
/// parents: New parents
///
/// # Returns
///
/// Names of the removed tags
pub fn remove_tags<B: Branch>(
    branch: B,
    graph: &Graph,
    old_tip: RevisionId,
    parents: &[RevisionId],
) -> std::result::Result<Vec<String>, crate::tags::Error> {
    let mut tags = branch.tags();
    let reverse_tags = tags.get_reverse_tag_dict();

    let ancestors = graph.find_unique_ancestors(old_tip, parents);
    let mut removed_tags = Vec::new();

    for (revid, revid_tags) in reverse_tags.into_iter() {
        if !ancestors.contains(&revid) {
            continue;
        }
        for tag in revid_tags {
            tags.delete_tag(tag.as_str())?;
            removed_tags.push(tag);
        }
    }
    Ok(removed_tags)
}
