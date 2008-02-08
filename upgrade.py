# Copyright (C) 2006 by Jelmer Vernooij
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
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

from bzrlib.errors import BzrError, InvalidRevisionId
from bzrlib.trace import info, mutter
import bzrlib.ui as ui

from errors import RebaseNotPresent
from mapping import parse_revision_id

class UpgradeChangesContent(BzrError):
    """Inconsistency was found upgrading the mapping of a revision."""
    _fmt = """Upgrade will change contents in revision %(revid)s. Use --allow-changes to override."""

    def __init__(self, revid):
        self.revid = revid



def create_upgraded_revid(revid, mapping_suffix, upgrade_suffix="-upgrade"):
    """Create a new revision id for an upgraded version of a revision.
    
    Prevents suffix to be appended needlessly.

    :param revid: Original revision id.
    :return: New revision id
    """
    if revid.endswith(upgrade_suffix):
        return revid[0:revid.rfind("-svn")] + mapping_suffix + upgrade_suffix
    else:
        return revid + mapping_suffix + upgrade_suffix


def upgrade_workingtree(wt, svn_repository, allow_changes=False, verbose=False):
    """Upgrade a working tree.

    :param svn_repository: Subversion repository object
    """
    renames = upgrade_branch(wt.branch, svn_repository, allow_changes=allow_changes, verbose=verbose)
    last_revid = wt.branch.last_revision()
    wt.set_parent_trees([(last_revid, wt.branch.repository.revision_tree(last_revid))])
    # TODO: Should also adjust file ids in working tree if necessary
    return renames


def upgrade_branch(branch, svn_repository, allow_changes=False, verbose=False):
    """Upgrade a branch to the current mapping version.
    
    :param branch: Branch to upgrade.
    :param svn_repository: Repository to fetch new revisions from
    :param allow_changes: Allow changes in mappings.
    :param verbose: Whether to print verbose list of rewrites
    """
    revid = branch.last_revision()
    renames = upgrade_repository(branch.repository, svn_repository, 
              revision_id=revid, allow_changes=allow_changes, verbose=verbose)
    if len(renames) > 0:
        branch.generate_revision_history(renames[revid])
    return renames


def check_revision_changed(oldrev, newrev):
    """Check if two revisions are different. This is exactly the same 
    as Revision.equals() except that it does not check the revision_id."""
    if (newrev.inventory_sha1 != oldrev.inventory_sha1 or
        newrev.timestamp != oldrev.timestamp or
        newrev.message != oldrev.message or
        newrev.timezone != oldrev.timezone or
        newrev.committer != oldrev.committer or
        newrev.properties != oldrev.properties):
        raise UpgradeChangesContent(oldrev.revision_id)


def generate_upgrade_map(new_mapping, revs):
    """Generate an upgrade map for use by bzr-rebase.

    :param new_mapping: BzrSvnMapping to upgrade revisions to.
    :param revs: Iterator over revisions to upgrade.
    :return: Map from old revids as keys, new revids as values stored in a 
             dictionary.
    """
    rename_map = {}
    pb = ui.ui_factory.nested_progress_bar()
    # Create a list of revisions that can be renamed during the upgade
    try:
        for revid in revs:
            pb.update('gather revision information', revs.index(revid), len(revs))
            try:
                (uuid, bp, rev, mapping) = parse_revision_id(revid)
            except InvalidRevisionId:
                # Not a bzr-svn revision, nothing to do
                continue
            newrevid = new_mapping.generate_revision_id(uuid, rev, bp)
            if revid == newrevid:
                continue
            rename_map[revid] = newrevid
    finally:
        pb.finished()

    return rename_map

MIN_REBASE_VERSION = (0, 2)

def check_rebase_version():
    """Check what version of bzr-rebase is installed.

    Raises an exception when the version installed is older than 
    MIN_REBASE_VERSION.

    :raises RebaseNotPresent: Raised if bzr-rebase is not installed or too old.
    """
    try:
        from bzrlib.plugins.rebase import version_info as rebase_version_info
        if rebase_version_info[:2] < MIN_REBASE_VERSION:
            raise RebaseNotPresent("Version %r present, at least %r required" 
                                   % (rebase_version_info, MIN_REBASE_VERSION))
    except ImportError, e:
        raise RebaseNotPresent(e)


def create_upgrade_plan(repository, svn_repository, new_mapping,
                        revision_id=None, allow_changes=False):
    """Generate a rebase plan for upgrading revisions.

    :param repository: Repository to do upgrade in
    :param svn_repository: Subversion repository to fetch new revisions from.
    :param new_mapping: New mapping to use.
    :param revision_id: Revision to upgrade (None for all revisions in 
        repository.)
    :param allow_changes: Whether an upgrade is allowed to change the contents
        of revisions.
    :return: Tuple with a rebase plan and map of renamed revisions.
    """
    from bzrlib.plugins.rebase.rebase import generate_transpose_plan
    check_rebase_version()

    graph = repository.get_revision_graph(revision_id)
    upgrade_map = generate_upgrade_map(new_mapping, graph.keys())
   
    # Make sure all the required current version revisions are present
    for revid in upgrade_map.values():
        if not repository.has_revision(revid):
            repository.fetch(svn_repository, revid)

    if not allow_changes:
        for oldrevid, newrevid in upgrade_map.items():
            oldrev = repository.get_revision(oldrevid)
            newrev = repository.get_revision(newrevid)
            check_revision_changed(oldrev, newrev)

    plan = generate_transpose_plan(graph, upgrade_map, 
      repository.revision_parents,
      lambda revid: create_upgraded_revid(revid, new_mapping.upgrade_suffix))
    def remove_parents((oldrevid, (newrevid, parents))):
        return (oldrevid, newrevid)
    upgrade_map.update(dict(map(remove_parents, plan.items())))

    return (plan, upgrade_map)

 
def upgrade_repository(repository, svn_repository, new_mapping=None,
                       revision_id=None, allow_changes=False, verbose=False):
    """Upgrade the revisions in repository until the specified stop revision.

    :param repository: Repository in which to upgrade.
    :param svn_repository: Repository to fetch new revisions from.
    :param new_mapping: New mapping.
    :param revision_id: Revision id up until which to upgrade, or None for 
                        all revisions.
    :param allow_changes: Allow changes to mappings.
    :param verbose: Whether to print list of rewrites
    :return: Dictionary of mapped revisions
    """
    check_rebase_version()
    from bzrlib.plugins.rebase.rebase import (
        replay_snapshot, rebase, rebase_todo)

    if new_mapping is None:
        new_mapping = svn_repository.get_mapping()

    # Find revisions that need to be upgraded, create
    # dictionary with revision ids in key, new parents in value
    try:
        repository.lock_write()
        svn_repository.lock_read()
        (plan, revid_renames) = create_upgrade_plan(repository, svn_repository, 
                                                    new_mapping,
                                                    revision_id=revision_id,
                                                    allow_changes=allow_changes)
        if verbose:
            for revid in rebase_todo(repository, plan):
                info("%s -> %s" % (revid, plan[revid][0]))
        def fix_revid(revid):
            try:
                (uuid, bp, rev, mapping) = parse_revision_id(revid)
            except InvalidRevisionId:
                return revid
            return new_mapping.generate_revision_id(uuid, rev, bp)
        def replay(repository, oldrevid, newrevid, new_parents):
            return replay_snapshot(repository, oldrevid, newrevid, new_parents,
                                   revid_renames, fix_revid)
        rebase(repository, plan, replay)
        return revid_renames
    finally:
        repository.unlock()
        svn_repository.unlock()
