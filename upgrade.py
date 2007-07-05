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
from bzrlib.trace import mutter
import bzrlib.ui as ui

from errors import RebaseNotPresent
from revids import (generate_svn_revision_id, parse_svn_revision_id, 
                    MAPPING_VERSION,  unescape_svn_path)
from scheme import BranchingScheme

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


def upgrade_branch(branch, svn_repository, allow_changes=False):
    """Upgrade a branch to the current mapping version.
    
    :param branch: Branch to upgrade.
    :param svn_repository: Repository to fetch new revisions from
    :param allow_changes: Allow changes in mappings.
    """
    revid = branch.last_revision()
    renames = upgrade_repository(branch.repository, svn_repository, 
              revid, allow_changes)
    mutter('renames %r' % renames)
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


def upgrade_repository(repository, svn_repository, revision_id=None, 
                       allow_change=False):
    """Upgrade the revisions in repository until the specified stop revision.

    :param repository: Repository in which to upgrade.
    :param svn_repository: Repository to fetch new revisions from.
    :param revision_id: Revision id up until which to upgrade, or None for 
                        all revisions.
    :param allow_change: Allow changes to mappings.
    :return: Dictionary of mapped revisions
    """
    try:
        from bzrlib.plugins.rebase.rebase import replay_snapshot, generate_transpose_plan, rebase
    except ImportError, e:
        raise RebaseNotPresent(e)
    rename_map = {}

    try:
        repository.lock_write()
        svn_repository.lock_read()
        # Find revisions that need to be upgraded, create
        # dictionary with revision ids in key, new parents in value
        graph = repository.get_revision_graph(revision_id)
        pb = ui.ui_factory.nested_progress_bar()
        i = 0
        try:
            for revid in graph:
                pb.update('gather revision information', i, len(graph))
                i += 1
                try:
                    (uuid, bp, rev, scheme, _) = parse_legacy_revision_id(revid)
                except InvalidRevisionId:
                    # Not a bzr-svn revision, nothing to do
                    continue
                if scheme is None:
                    scheme = BranchingScheme.guess_scheme(bp)
                newrevid = generate_svn_revision_id(uuid, rev, bp, scheme)
                if not repository.has_revision(newrevid) and \
                   not svn_repository.has_revision(newrevid):
                    # Not a revision that can be upgraded using the remote repository, 
                    # nothing to do
                    if hasattr(svn_repository, 'uuid') and \
                            svn_repository.uuid == uuid:
                        mutter("Remote repository doesn't have %r" % newrevid)
                    continue
                rename_map[revid] = newrevid
                if not allow_change:
                    oldrev = repository.get_revision(revid)
                    newrev = svn_repository.get_revision(newrevid)
                    check_revision_changed(oldrev, newrev)
        finally:
            pb.finished()
        
        # Make sure all the required current version revisions are present
        for revid in rename_map.values():
            if not repository.has_revision(revid):
                repository.fetch(svn_repository, revid)

        plan = generate_transpose_plan(repository, graph, rename_map, 
                                       lambda rev: create_upgraded_revid(rev.revision_id))
        mutter('rebase plan: %r' % plan)
        rebase(repository, plan, replay_snapshot)
        def remove_parents((oldrevid, (newrevid, parents))):
            return (oldrevid, newrevid)
        return dict(map(remove_parents, plan.items()))
    finally:
        repository.unlock()
        svn_repository.unlock()
