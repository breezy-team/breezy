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
from revids import (generate_svn_revision_id, parse_svn_revision_id, 
                    MAPPING_VERSION,  unescape_svn_path)
from scheme import BranchingScheme, guess_scheme_from_branch_path

class UpgradeChangesContent(BzrError):
    """Inconsistency was found upgrading the mapping of a revision."""
    _fmt = """Upgrade will change contents in revision %(revid)s. Use --allow-changes to override."""

    def __init__(self, revid):
        self.revid = revid


def parse_legacy_revision_id(revid):
    """Try to parse a legacy Subversion revision id.
    
    :param revid: Revision id to parse
    :return: tuple with (uuid, branch_path, revision number, scheme, mapping version)
    """
    if revid.startswith("svn-v1:"):
        revid = revid[len("svn-v1:"):]
        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]
        branch_path = unescape_svn_path(revid[fash+1:])
        revnum = int(revid[0:at])
        assert revnum >= 0
        return (uuid, branch_path, revnum, None, 1)
    elif revid.startswith("svn-v2:"):
        revid = revid[len("svn-v2:"):]
        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]
        branch_path = unescape_svn_path(revid[fash+1:])
        revnum = int(revid[0:at])
        assert revnum >= 0
        return (uuid, branch_path, revnum, None, 2)
    elif revid.startswith("svn-v3-"):
        (uuid, bp, rev, scheme) = parse_svn_revision_id(revid)
        if scheme == "undefined":
            scheme = None
        return (uuid, bp, rev, scheme, 3)

    raise InvalidRevisionId(revid, None)


def create_upgraded_revid(revid):
    """Create a new revision id for an upgraded version of a revision.
    
    Prevents suffix to be appended needlessly.

    :param revid: Original revision id.
    :return: New revision id
    """
    suffix = "-svn%d-upgrade" % MAPPING_VERSION
    if revid.endswith("-upgrade"):
        return revid[0:revid.rfind("-svn")] + suffix
    else:
        return revid + suffix


def upgrade_workingtree(wt, svn_repository, allow_changes=False, verbose=False):
    upgrade_branch(wt.branch, svn_repository, allow_changes=allow_changes, verbose=verbose)
    last_revid = wt.branch.last_revision()
    wt.set_parent_trees([(last_revid, wt.branch.repository.revision_tree(last_revid))])
    # TODO: Should also adjust file ids in working tree if necessary


def upgrade_branch(branch, svn_repository, allow_changes=False, verbose=False):
    """Upgrade a branch to the current mapping version.
    
    :param branch: Branch to upgrade.
    :param svn_repository: Repository to fetch new revisions from
    :param allow_changes: Allow changes in mappings.
    :param verbose: Whether to print verbose list of rewrites
    """
    revid = branch.last_revision()
    renames = upgrade_repository(branch.repository, svn_repository, 
              revid, allow_changes=allow_changes, verbose=verbose)
    if len(renames) > 0:
        branch.generate_revision_history(renames[revid])


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


def generate_upgrade_map(revs):
    rename_map = {}
    pb = ui.ui_factory.nested_progress_bar()
    # Create a list of revisions that can be renamed during the upgade
    try:
        for revid in revs:
            pb.update('gather revision information', revs.index(revid), len(revs))
            try:
                (uuid, bp, rev, scheme, _) = parse_legacy_revision_id(revid)
            except InvalidRevisionId:
                # Not a bzr-svn revision, nothing to do
                continue
            if scheme is None:
                scheme = guess_scheme_from_branch_path(bp)
            newrevid = generate_svn_revision_id(uuid, rev, bp, scheme)
            rename_map[revid] = newrevid
    finally:
        pb.finished()

    return rename_map

MIN_REBASE_VERSION = (0, 2)

def check_rebase_version():
    try:
        from bzrlib.plugins.rebase import version_info as rebase_version_info
        if rebase_version_info[:2] < MIN_REBASE_VERSION:
            raise RebaseNotPresent("Version %r present, at least %r required" 
                                   % (rebase_version_info, MIN_REBASE_VERSION))
    except ImportError, e:
        raise RebaseNotPresent(e)


def create_upgrade_plan(repository, svn_repository, revision_id=None,
                        allow_changes=False):
    """Generate a rebase plan for upgrading revisions.

    :param repository: Repository to do upgrade in
    :param svn_repository: Subversion repository to fetch new revisions from.
    :param revision_id: Revision to upgrade (None for all revisions in 
        repository.)
    :param allow_changes: Whether an upgrade is allowed to change the contents
        of revisions.
    :return: Tuple with a rebase plan and map of renamed revisions.
    """
    from bzrlib.plugins.rebase.rebase import generate_transpose_plan
    check_rebase_version()

    graph = repository.get_revision_graph(revision_id)
    upgrade_map = generate_upgrade_map(graph.keys())
   
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
                                   create_upgraded_revid)
    def remove_parents((oldrevid, (newrevid, parents))):
        return (oldrevid, newrevid)
    upgrade_map.update(dict(map(remove_parents, plan.items())))

    return (plan, upgrade_map)

 
def upgrade_repository(repository, svn_repository, revision_id=None, 
                       allow_changes=False, verbose=False):
    """Upgrade the revisions in repository until the specified stop revision.

    :param repository: Repository in which to upgrade.
    :param svn_repository: Repository to fetch new revisions from.
    :param revision_id: Revision id up until which to upgrade, or None for 
                        all revisions.
    :param allow_changes: Allow changes to mappings.
    :param verbose: Whether to print list of rewrites
    :return: Dictionary of mapped revisions
    """
    check_rebase_version()
    from bzrlib.plugins.rebase.rebase import (
        replay_snapshot, rebase, rebase_todo)

    # Find revisions that need to be upgraded, create
    # dictionary with revision ids in key, new parents in value
    try:
        repository.lock_write()
        svn_repository.lock_read()
        (plan, revid_renames) = create_upgrade_plan(repository, svn_repository, 
                                                    revision_id=revision_id,
                                                    allow_changes=allow_changes)
        if verbose:
            for revid in rebase_todo(repository, plan):
                info("%s -> %s" % (revid, plan[revid][0]))
        def fix_revid(revid):
            try:
                (uuid, bp, rev, scheme, _) = parse_legacy_revision_id(revid)
            except InvalidRevisionId:
                return revid
            if scheme is None:
                scheme = guess_scheme_from_branch_path(bp)
            return generate_svn_revision_id(uuid, rev, bp, scheme)
        def replay(repository, oldrevid, newrevid, new_parents):
            return replay_snapshot(repository, oldrevid, newrevid, new_parents,
                                   revid_renames, fix_revid)
        rebase(repository, plan, replay)
        return revid_renames
    finally:
        repository.unlock()
        svn_repository.unlock()
