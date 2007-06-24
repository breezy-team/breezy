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

from bzrlib.config import Config
from bzrlib.errors import BzrError, InvalidRevisionId
from bzrlib.trace import mutter
import bzrlib.ui as ui

from revids import (generate_svn_revision_id, parse_svn_revision_id, 
                    MAPPING_VERSION,  unescape_svn_path)
from scheme import BranchingScheme

class UpgradeChangesContent(BzrError):
    """Inconsistency was found upgrading the mapping of a revision."""
    _fmt = """Upgrade will change contents in revision %(revid)s. Use --allow-changes to override."""

    def __init__(self, revid):
        self.revid = revid


# Change the parent of a revision
def change_revision_parent(repository, oldrevid, newrevid, new_parents):
    """Create a copy of a revision with different parents.

    :param repository: Repository in which the revision is present.
    :param oldrevid: Revision id of the revision to copy.
    :param newrevid: Revision id of the revision to create.
    :param new_parents: Revision ids of the new parent revisions.
    """
    assert isinstance(new_parents, list)
    mutter('creating copy %r of %r with new parents %r' % (newrevid, oldrevid, new_parents))
    oldrev = repository.get_revision(oldrevid)

    builder = repository.get_commit_builder(branch=None, parents=new_parents, 
                                  config=Config(),
                                  committer=oldrev.committer,
                                  timestamp=oldrev.timestamp,
                                  timezone=oldrev.timezone,
                                  revprops=oldrev.properties,
                                  revision_id=newrevid)

    # Check what new_ie.file_id should be
    # use old and new parent inventories to generate new_id map
    old_parents = oldrev.parent_ids
    new_id = {}
    for (oldp, newp) in zip(old_parents, new_parents):
        oldinv = repository.get_revision_inventory(oldp)
        newinv = repository.get_revision_inventory(newp)
        for path, ie in oldinv.iter_entries():
            if newinv.has_filename(path):
                new_id[ie.file_id] = newinv.path2id(path)

    i = 0
    class MapTree:
        def __init__(self, oldtree, map):
            self.oldtree = oldtree
            self.map = map

        def old_id(self, file_id):
            for x in self.map:
                if self.map[x] == file_id:
                    return x
            return file_id

        def get_file_sha1(self, file_id, path=None):
            return self.oldtree.get_file_sha1(file_id=self.old_id(file_id), 
                                              path=path)

        def get_file(self, file_id):
            return self.oldtree.get_file(self.old_id(file_id=file_id))

        def is_executable(self, file_id, path=None):
            return self.oldtree.is_executable(self.old_id(file_id=file_id), 
                                              path=path)

    oldtree = MapTree(repository.revision_tree(oldrevid), new_id)
    oldinv = repository.get_revision_inventory(oldrevid)
    total = len(oldinv)
    pb = ui.ui_factory.nested_progress_bar()
    transact = repository.get_transaction()
    try:
        for path, ie in oldinv.iter_entries():
            pb.update('upgrading file', i, total)
            i += 1
            new_ie = ie.copy()
            if new_ie.revision == oldrevid:
                new_ie.revision = None
            def lookup(file_id):
                try:
                    return new_id[file_id]
                except KeyError:
                    return file_id

            new_ie.file_id = lookup(new_ie.file_id)
            new_ie.parent_id = lookup(new_ie.parent_id)
            builder.record_entry_contents(new_ie, 
                   map(repository.get_revision_inventory, new_parents), 
                   path, oldtree)
    finally:
        pb.finished()

    builder.finish_inventory()
    return builder.commit(oldrev.message)


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


def upgrade_branch(branch, svn_repository, allow_change=False):
    """Upgrade a branch to the current mapping version.
    
    :param branch: Branch to upgrade.
    :param svn_repository: Repository to fetch new revisions from
    :param allow_change: Allow changes in mappings.
    """
    revid = branch.last_revision()
    renames = upgrade_repository(branch.repository, svn_repository, 
              revid, allow_change)
    mutter('renames %r' % renames)
    if len(renames) > 0:
        branch.generate_revision_history(renames[revid])


def revision_changed(oldrev, newrev):
    """Check if two revisions are different. This is exactly the same 
    as Revision.equals() except that it does not check the revision_id."""
    if (newrev.inventory_sha1 != oldrev.inventory_sha1 or
        newrev.timestamp != oldrev.timestamp or
        newrev.message != oldrev.message or
        newrev.timezone != oldrev.timezone or
        newrev.committer != oldrev.committer or
        newrev.properties != oldrev.properties):
        return True
    return False


def upgrade_repository(repository, svn_repository, revision_id=None, 
                       allow_change=False):
    """Upgrade the revisions in repository until the specified stop revision.

    :param repository: Repository in which to upgrade.
    :param svn_repository: Repository to fetch new revisions from.
    :param revision_id: Revision id up until which to upgrade, or None for 
                        all revisions.
    :param allow_change: Allow changes to mappings.
    """
    needed_revs = []
    needs_upgrading = []
    new_parents = {}
    rename_map = {}

    try:
        repository.lock_write()
        svn_repository.lock_read()
        # Find revisions that need to be upgraded, create
        # dictionary with revision ids in key, new parents in value
        graph = repository.get_revision_graph(revision_id)
        def find_children(revid):
            for x in graph:
                if revid in graph[x]:
                    yield x
        pb = ui.ui_factory.nested_progress_bar()
        i = 0
        try:
            for revid in graph:
                pb.update('gather revision information', i, len(graph))
                i += 1
                try:
                    (uuid, bp, rev, scheme, _) = parse_legacy_revision_id(revid)
                    if scheme is None:
                        scheme = BranchingScheme.guess_scheme(bp)
                    newrevid = generate_svn_revision_id(uuid, rev, bp, scheme)
                    if svn_repository.has_revision(newrevid):
                        rename_map[revid] = newrevid
                        if not repository.has_revision(newrevid):
                            if not allow_change:
                                oldrev = repository.get_revision(revid)
                                newrev = svn_repository.get_revision(newrevid)
                                if revision_changed(oldrev, newrev):
                                    raise UpgradeChangesContent(revid)
                            needed_revs.append(newrevid)
                        continue
                except InvalidRevisionId:
                    pass
                new_parents[revid] = []
                for parent in graph[revid]:
                    try:
                        (uuid, bp, rev, scheme, version) = parse_legacy_revision_id(parent)

                        if scheme is None:
                            scheme = BranchingScheme.guess_scheme(bp)
                        new_parent = generate_svn_revision_id(uuid, rev, bp, scheme)
                        if new_parent != parent:
                            if not repository.has_revision(revid):
                                needed_revs.append(new_parent)
                            needs_upgrading.append(revid)

                            if not allow_change:
                                oldrev = repository.get_revision(parent)
                                newrev = svn_repository.get_revision(new_parent)
                                if revision_changed(oldrev, newrev):
                                    raise UpgradeChangesContent(parent)
                        new_parents[revid].append(new_parent)
                    except InvalidRevisionId:
                        new_parents[revid].append(parent)
        finally:
            pb.finished()

        # Make sure all the required current version revisions are present
        pb = ui.ui_factory.nested_progress_bar()
        i = 0
        try:
            for revid in needed_revs:
                pb.update('fetching new revisions', i, len(needed_revs))
                repository.fetch(svn_repository, revid)
                i += 1
        finally:
            pb.finished()

        pb = ui.ui_factory.nested_progress_bar()
        i = 0
        total = len(needs_upgrading)
        try:
            while len(needs_upgrading) > 0:
                revid = needs_upgrading.pop()
                pb.update('upgrading revisions', i, total)
                i += 1
                newrevid = create_upgraded_revid(revid)
                rename_map[revid] = newrevid
                if repository.has_revision(newrevid):
                    continue
                change_revision_parent(repository, revid, newrevid, new_parents[revid])
                for childrev in find_children(revid):
                    if not new_parents.has_key(childrev):
                        new_parents = repository.revision_parents(childrev)
                    def replace_parent(x):
                        if x == revid:
                            return newrevid
                        return x
                    if (revid in new_parents[childrev] and 
                        not childrev in needs_upgrading):
                        new_parents[childrev] = map(replace_parent, new_parents[childrev])
                        needs_upgrading.append(childrev)
        finally:
            pb.finished()
        return rename_map
    finally:
        repository.unlock()
        svn_repository.unlock()
