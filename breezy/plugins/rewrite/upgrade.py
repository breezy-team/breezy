# Copyright (C) 2006-2009 by Jelmer Vernooij
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Upgrading revisions made with older versions of the mapping."""

from ... import osutils, trace, ui
from ...errors import BzrError
from .rebase import (
    CommitBuilderRevisionRewriter,
    generate_transpose_plan,
    rebase,
    rebase_todo,
)


class UpgradeChangesContent(BzrError):
    """Inconsistency was found upgrading the mapping of a revision."""

    _fmt = """Upgrade will change contents in revision %(revid)s. Use --allow-changes to override."""

    def __init__(self, revid):
        """Initialize the error with the revision ID that has content changes.

        Args:
            revid: The revision ID that would have content changes during upgrade.
        """
        self.revid = revid


def create_deterministic_revid(revid, new_parents):
    """Create a new deterministic revision id with specified new parents.

    Prevents suffix to be appended needlessly.

    :param revid: Original revision id.
    :return: New revision id
    """
    if "-rebase-" in revid:
        revid = revid[0 : revid.rfind("-rebase-")]
    return revid + "-rebase-" + osutils.sha_string(":".join(new_parents))[:8]


def upgrade_tags(
    tags,
    repository,
    generate_rebase_map,
    determine_new_revid,
    allow_changes=False,
    verbose=False,
    branch_renames=None,
    branch_ancestry=None,
):
    """Upgrade a tags dictionary."""
    renames = {}
    if branch_renames is not None:
        renames.update(branch_renames)
    pb = ui.ui_factory.nested_progress_bar()
    try:
        tags_dict = tags.get_tag_dict()
        for i, (name, revid) in enumerate(tags_dict.iteritems()):
            pb.update("upgrading tags", i, len(tags_dict))
            if revid not in renames:
                try:
                    repository.lock_read()
                    revid_exists = repository.has_revision(revid)
                finally:
                    repository.unlock()
                if revid_exists:
                    renames.update(
                        upgrade_repository(
                            repository,
                            generate_rebase_map,
                            determine_new_revid,
                            revision_id=revid,
                            allow_changes=allow_changes,
                            verbose=verbose,
                        )
                    )
            if revid in renames and (
                branch_ancestry is None or revid not in branch_ancestry
            ):
                tags.set_tag(name, renames[revid])
    finally:
        pb.finished()


def upgrade_branch(
    branch, generate_rebase_map, determine_new_revid, allow_changes=False, verbose=False
):
    """Upgrade a branch to the current mapping version.

    :param branch: Branch to upgrade.
    :param foreign_repository: Repository to fetch new revisions from
    :param allow_changes: Allow changes in mappings.
    :param verbose: Whether to print verbose list of rewrites
    """
    revid = branch.last_revision()
    renames = upgrade_repository(
        branch.repository,
        generate_rebase_map,
        determine_new_revid,
        revision_id=revid,
        allow_changes=allow_changes,
        verbose=verbose,
    )
    if revid in renames:
        branch.generate_revision_history(renames[revid])
    ancestry = branch.repository.get_ancestry(branch.last_revision(), topo_sorted=False)
    upgrade_tags(
        branch.tags,
        branch.repository,
        generate_rebase_map,
        determine_new_revid,
        allow_changes=allow_changes,
        verbose=verbose,
        branch_renames=renames,
        branch_ancestry=ancestry,
    )
    return renames


def check_revision_changed(oldrev, newrev):
    """Check if two revisions are different. This is exactly the same
    as Revision.equals() except that it does not check the revision_id.
    """
    if (
        newrev.inventory_sha1 != oldrev.inventory_sha1
        or newrev.timestamp != oldrev.timestamp
        or newrev.message != oldrev.message
        or newrev.timezone != oldrev.timezone
        or newrev.committer != oldrev.committer
        or newrev.properties != oldrev.properties
    ):
        raise UpgradeChangesContent(oldrev.revision_id)


def create_upgrade_plan(
    repository,
    generate_rebase_map,
    determine_new_revid,
    revision_id=None,
    allow_changes=False,
):
    """Generate a rebase plan for upgrading revisions.

    :param repository: Repository to do upgrade in
    :param foreign_repository: Subversion repository to fetch new revisions
        from.
    :param new_mapping: New mapping to use.
    :param revision_id: Revision to upgrade (None for all revisions in
        repository.)
    :param allow_changes: Whether an upgrade is allowed to change the contents
        of revisions.
    :return: Tuple with a rebase plan and map of renamed revisions.
    """
    graph = repository.get_graph()
    upgrade_map = generate_rebase_map(revision_id)

    if not allow_changes:
        for oldrevid, newrevid in upgrade_map.iteritems():
            oldrev = repository.get_revision(oldrevid)
            newrev = repository.get_revision(newrevid)
            check_revision_changed(oldrev, newrev)

    heads = repository.all_revision_ids() if revision_id is None else [revision_id]

    plan = generate_transpose_plan(
        graph.iter_ancestry(heads), upgrade_map, graph, determine_new_revid
    )

    def remove_parents(entry):
        (oldrevid, (newrevid, _parents)) = entry
        return (oldrevid, newrevid)

    upgrade_map.update(dict(map(remove_parents, plan.iteritems())))

    return (plan, upgrade_map)


def upgrade_repository(
    repository,
    generate_rebase_map,
    determine_new_revid,
    revision_id=None,
    allow_changes=False,
    verbose=False,
):
    """Upgrade the revisions in repository until the specified stop revision.

    :param repository: Repository in which to upgrade.
    :param foreign_repository: Repository to fetch new revisions from.
    :param new_mapping: New mapping.
    :param revision_id: Revision id up until which to upgrade, or None for
                        all revisions.
    :param allow_changes: Allow changes to mappings.
    :param verbose: Whether to print list of rewrites
    :return: Dictionary of mapped revisions
    """
    # Find revisions that need to be upgraded, create
    # dictionary with revision ids in key, new parents in value
    with repository.lock_write():
        (plan, revid_renames) = create_upgrade_plan(
            repository,
            generate_rebase_map,
            determine_new_revid,
            revision_id=revision_id,
            allow_changes=allow_changes,
        )
        if verbose:
            for revid in rebase_todo(repository, plan):
                trace.note(f"{revid} -> {plan[revid][0]}")
        rebase(repository, plan, CommitBuilderRevisionRewriter(repository))
        return revid_renames
