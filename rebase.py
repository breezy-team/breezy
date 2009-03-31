# Copyright (C) 2006-2007 by Jelmer Vernooij
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
"""Rebase."""

from bzrlib.config import Config
from bzrlib.errors import (BzrError, NoSuchFile, UnknownFormatError,
                           NoCommonAncestor, NoSuchId, UnrelatedBranches)
from bzrlib.generate_ids import gen_revision_id
from bzrlib.graph import FrozenHeadsCache
from bzrlib.merge import Merger
from bzrlib import osutils
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter
from bzrlib.tsort import topo_sort
import bzrlib.ui as ui

from maptree import MapTree, map_file_ids
import os

REBASE_PLAN_FILENAME = 'rebase-plan'
REBASE_CURRENT_REVID_FILENAME = 'rebase-current'
REBASE_PLAN_VERSION = 1
REVPROP_REBASE_OF = 'rebase-of'

def rebase_plan_exists(wt):
    """Check whether there is a rebase plan present.

    :param wt: Working tree for which to check.
    :return: boolean
    """
    try:
        return wt._transport.get_bytes(REBASE_PLAN_FILENAME) != ''
    except NoSuchFile:
        return False


def read_rebase_plan(wt):
    """Read a rebase plan file.

    :param wt: Working Tree for which to write the plan.
    :return: Tuple with last revision info and replace map.
    """
    text = wt._transport.get_bytes(REBASE_PLAN_FILENAME)
    if text == '':
        raise NoSuchFile(REBASE_PLAN_FILENAME)
    return unmarshall_rebase_plan(text)


def write_rebase_plan(wt, replace_map):
    """Write a rebase plan file.

    :param wt: Working Tree for which to write the plan.
    :param replace_map: Replace map (old revid -> (new revid, new parents))
    """
    content = marshall_rebase_plan(wt.branch.last_revision_info(), replace_map)
    assert type(content) == str
    wt._transport.put_bytes(REBASE_PLAN_FILENAME, content)


def remove_rebase_plan(wt):
    """Remove a rebase plan file.

    :param wt: Working Tree for which to remove the plan.
    """
    wt._transport.put_bytes(REBASE_PLAN_FILENAME, '')


def marshall_rebase_plan(last_rev_info, replace_map):
    """Marshall a rebase plan.

    :param last_rev_info: Last revision info tuple.
    :param replace_map: Replace map (old revid -> (new revid, new parents))
    :return: string
    """
    ret = "# Bazaar rebase plan %d\n" % REBASE_PLAN_VERSION
    ret += "%d %s\n" % last_rev_info
    for oldrev in replace_map:
        (newrev, newparents) = replace_map[oldrev]
        ret += "%s %s" % (oldrev, newrev) + \
            "".join([" %s" % p for p in newparents]) + "\n"
    return ret


def unmarshall_rebase_plan(text):
    """Unmarshall a rebase plan.

    :param text: Text to parse
    :return: Tuple with last revision info, replace map.
    """
    lines = text.split('\n')
    # Make sure header is there
    if lines[0] != "# Bazaar rebase plan %d" % REBASE_PLAN_VERSION:
        raise UnknownFormatError(lines[0])

    pts = lines[1].split(" ", 1)
    last_revision_info = (int(pts[0]), pts[1])
    replace_map = {}
    for l in lines[2:]:
        if l == "":
            # Skip empty lines
            continue
        pts = l.split(" ")
        replace_map[pts[0]] = (pts[1], tuple(pts[2:]))
    return (last_revision_info, replace_map)


def regenerate_default_revid(repository, revid):
    """Generate a revision id for the rebase of an existing revision.
    
    :param repository: Repository in which the revision is present.
    :param revid: Revision id of the revision that is being rebased.
    :return: new revision id."""
    rev = repository.get_revision(revid)
    return gen_revision_id(rev.committer, rev.timestamp)


def generate_simple_plan(todo_set, start_revid, stop_revid, onto_revid, graph,
    generate_revid, skip_full_merged=False):
    """Create a simple rebase plan that replays history based 
    on one revision being replayed on top of another.

    :param todo_set: A set of revisions to rebase. Only the revisions from
        stop_revid back through the left hand ancestry are rebased; other
        revisions are ignored (and references to them are preserved).
    :param start_revid: Id of revision at which to start replaying
    :param stop_revid: Id of revision until which to stop replaying
    :param onto_revid: Id of revision on top of which to replay
    :param graph: Graph object
    :param generate_revid: Function for generating new revision ids
    :param skip_full_merged: Skip revisions that merge already merged 
                             revisions.

    :return: replace map
    """
    assert start_revid is None or start_revid in todo_set, \
        "invalid start revid(%r), todo_set(%r)" % (start_revid, todo_set)
    assert stop_revid is None or stop_revid in todo_set, "invalid stop_revid"
    replace_map = {}
    parent_map = graph.get_parent_map(todo_set)
    order = topo_sort(parent_map)
    left_most_path = []
    if stop_revid is None:
        stop_revid = order[-1]
    rev = stop_revid
    while rev in parent_map:
        left_most_path.append(rev)
        if rev == start_revid:
            # manual specified early-stop
            break
        rev = parent_map[rev][0]
    left_most_path.reverse()
    if start_revid is None:
        # We need a common base.
        lca = graph.find_lca(stop_revid, onto_revid)
        if lca == set([NULL_REVISION]):
            raise UnrelatedBranches()
    new_parent = onto_revid
    todo = left_most_path
    heads_cache = FrozenHeadsCache(graph)
    # XXX: The output replacemap'd parents should get looked up in some manner
    # by the heads cache? RBC 20080719
    for oldrevid in todo:
        oldparents = parent_map[oldrevid]
        assert isinstance(oldparents, tuple), "not tuple: %r" % oldparents
        if len(oldparents) > 1:
            additional_parents = heads_cache.heads(oldparents[1:])
            parents = [new_parent]
            for parent in parents:
                if parent in additional_parents and parent not in parents:
                    # Use as a parent
                    parent = replace_map.get(parent, (parent,))[0]
                    parents.append(parent)
            parents = tuple(parents)
            if len(parents) == 1 and skip_full_merged:
                continue
        else:
            parents = (new_parent,)
        newrevid = generate_revid(oldrevid)
        assert newrevid != oldrevid, "old and newrevid equal (%r)" % newrevid
        assert isinstance(parents, tuple), "parents not tuple: %r" % parents
        replace_map[oldrevid] = (newrevid, parents)
        new_parent = newrevid
    return replace_map


def generate_transpose_plan(ancestry, renames, graph, generate_revid):
    """Create a rebase plan that replaces a bunch of revisions
    in a revision graph.

    :param ancestry: Ancestry to consider
    :param renames: Renames of revision
    :param graph: Graph object
    :param generate_revid: Function for creating new revision ids
    """
    replace_map = {}
    todo = []
    children = {}
    parent_map = {}
    for r, ps in ancestry:
        if not children.has_key(r):
            children[r] = []
        if ps is None: # Ghost
            continue
        parent_map[r] = ps
        if not children.has_key(r):
            children[r] = []
        for p in ps:
            if not children.has_key(p):
                children[p] = []
            children[p].append(r)

    parent_map.update(graph.get_parent_map(filter(lambda x: not x in parent_map, renames.values())))

    # todo contains a list of revisions that need to 
    # be rewritten
    for r, v in renames.items():
        replace_map[r] = (v, parent_map[v])
        todo.append(r)

    total = len(todo)
    processed = set()
    i = 0
    pb = ui.ui_factory.nested_progress_bar()
    try:
        while len(todo) > 0:
            r = todo.pop()
            processed.add(r)
            i += 1
            pb.update('determining dependencies', i, total)
            # Add entry for them in replace_map
            for c in children[r]:
                if c in renames:
                    continue
                if replace_map.has_key(c):
                    parents = replace_map[c][1]
                else:
                    parents = parent_map[c]
                assert isinstance(parents, tuple), \
                        "Expected tuple of parents, got: %r" % parents
                # replace r in parents with replace_map[r][0]
                if not replace_map[r][0] in parents:
                    parents = list(parents)
                    parents[parents.index(r)] = replace_map[r][0]
                    parents = tuple(parents)
                replace_map[c] = (generate_revid(c), tuple(parents))
                if replace_map[c][0] == c:
                    del replace_map[c]
                elif c not in processed:
                    todo.append(c)
    finally:
        pb.finished()

    # Remove items from the map that already exist
    for revid in renames:
        if replace_map.has_key(revid):
            del replace_map[revid]

    return replace_map


def rebase_todo(repository, replace_map):
    """Figure out what revisions still need to be rebased.

    :param repository: Repository that contains the revisions
    :param replace_map: Replace map
    """
    for revid, parent_ids in replace_map.items():
        assert isinstance(parent_ids, tuple), "replace map parents not tuple"
        if not repository.has_revision(parent_ids[0]):
            yield revid


def rebase(repository, replace_map, replay_fn):
    """Rebase a working tree according to the specified map.

    :param repository: Repository that contains the revisions
    :param replace_map: Dictionary with revisions to (optionally) rewrite
    :param merge_fn: Function for replaying a revision
    """
    # Figure out the dependencies
    graph = repository.get_graph()
    todo = list(graph.iter_topo_order(replace_map.keys()))
    pb = ui.ui_factory.nested_progress_bar()
    try:
        for i, revid in enumerate(todo):
            pb.update('rebase revisions', i, len(todo))
            (newrevid, newparents) = replace_map[revid]
            assert isinstance(newparents, tuple), "Expected tuple for %r" % newparents
            if repository.has_revision(newrevid):
                # Was already converted, no need to worry about it again
                continue
            replay_fn(repository, revid, newrevid, newparents)
    finally:
        pb.finished()
        

def replay_snapshot(repository, oldrevid, newrevid, new_parents):
    """Replay a commit by simply commiting the same snapshot with different 
    parents.

    :param repository: Repository in which the revision is present.
    :param oldrevid: Revision id of the revision to copy.
    :param newrevid: Revision id of the revision to create.
    :param new_parents: Revision ids of the new parent revisions.
    """
    assert isinstance(new_parents, tuple), "replay_snapshot: Expected tuple for %r" % new_parents
    mutter('creating copy %r of %r with new parents %r' % 
                               (newrevid, oldrevid, new_parents))
    oldrev = repository.get_revision(oldrevid)

    revprops = dict(oldrev.properties)
    revprops[REVPROP_REBASE_OF] = oldrevid

    builder = repository.get_commit_builder(branch=None, 
                                            parents=new_parents, 
                                            config=Config(),
                                            committer=oldrev.committer,
                                            timestamp=oldrev.timestamp,
                                            timezone=oldrev.timezone,
                                            revprops=revprops,
                                            revision_id=newrevid)
    try:
        # Check what new_ie.file_id should be
        # use old and new parent inventories to generate new_id map
        nonghost_oldparents = tuple([p for p in oldrev.parent_ids if repository.has_revision(p)])
        nonghost_newparents = tuple([p for p in new_parents if repository.has_revision(p)])
        fileid_map = map_file_ids(repository, nonghost_oldparents, nonghost_newparents)
        oldtree = repository.revision_tree(oldrevid)
        mappedtree = MapTree(oldtree, fileid_map)
        pb = ui.ui_factory.nested_progress_bar()
        try:
            old_parent_invs = list(repository.iter_inventories(nonghost_oldparents))
            new_parent_invs = list(repository.iter_inventories(nonghost_newparents))
            for i, (path, old_ie) in enumerate(mappedtree.inventory.iter_entries()):
                pb.update('upgrading file', i, len(mappedtree.inventory))
                ie = old_ie.copy()
                # Either this file was modified last in this revision, 
                # in which case it has to be rewritten
                if old_ie.revision == oldrevid:
                    if repository.texts.has_key((ie.file_id, newrevid)):
                        # Use the existing text
                        ie.revision = newrevid
                    else:
                        # Create a new text
                        ie.revision = None
                else:
                    # or it was already there before the commit, in 
                    # which case the right revision should be used
                    # one of the old parents had this revision, so find that
                    # and then use the matching new parent
                    old_file_id = oldtree.inventory.path2id(path)
                    assert old_file_id is not None
                    ie = None
                    for (old_pinv, new_pinv) in zip(old_parent_invs, new_parent_invs):
                        if (old_pinv.has_id(old_file_id) and
                            old_pinv[old_file_id].revision == old_ie.revision):
                            try:
                                ie = new_pinv[old_ie.file_id].copy()
                            except NoSuchId:
                                raise ReplayParentsInconsistent(old_ie.file_id, old_ie.revision)
                            break
                    assert ie is not None
                builder.record_entry_contents(ie, new_parent_invs, path, mappedtree,
                        mappedtree.path_content_summary(path))
        finally:
            pb.finished()
        builder.finish_inventory()
        return builder.commit(oldrev.message)
    except:
        builder.abort()
        raise


def commit_rebase(wt, oldrev, newrevid):
    """Commit a rebase.
    
    :param wt: Mutable tree with the changes.
    :param oldrev: Revision info of new revision to commit.
    :param newrevid: New revision id."""
    assert oldrev.revision_id != newrevid, "Invalid revid %r" % newrevid
    revprops = dict(oldrev.properties)
    revprops[REVPROP_REBASE_OF] = oldrev.revision_id
    committer = wt.branch.get_config().username()
    authors = oldrev.get_apparent_authors()
    if oldrev.committer == committer:
        # No need to explicitly record the authors if the original 
        # committer is rebasing.
        if [oldrev.committer] == authors:
            authors = None
    else:
        authors.append(oldrev.committer)
    if 'author' in revprops:
        del revprops['author']
    if 'authors' in revprops:
        del revprops['authors']
    wt.commit(message=oldrev.message, timestamp=oldrev.timestamp, 
              timezone=oldrev.timezone, revprops=revprops, rev_id=newrevid,
              committer=committer, authors=authors)
    write_active_rebase_revid(wt, None)


def replay_determine_base(graph, oldrevid, oldparents, newrevid, newparents):
    """Determine the base for replaying a revision using merge.

    :param graph: Revision graph.
    :param oldrevid: Revid of old revision.
    :param oldparents: List of old parents revids.
    :param newrevid: Revid of new revision.
    :param newparents: List of new parents revids.
    :return: Revision id of the new new revision.
    """
    # If this was the first commit, no base is needed
    if len(oldparents) == 0:
        return NULL_REVISION

    # In the case of a "simple" revision with just one parent, 
    # that parent should be the base
    if len(oldparents) == 1:
        return oldparents[0]

    # In case the rhs parent(s) of the origin revision has already been merged
    # in the new branch, use diff between rhs parent and diff from 
    # original revision
    if len(newparents) == 1:
        # FIXME: Find oldparents entry that matches newparents[0] 
        # and return it
        return oldparents[1]

    try:
        return graph.find_unique_lca(*[oldparents[0],newparents[1]])
    except NoCommonAncestor:
        return oldparents[0]


def replay_delta_workingtree(wt, oldrevid, newrevid, newparents, 
                             merge_type=None):
    """Replay a commit in a working tree, with a different base.

    :param wt: Working tree in which to do the replays.
    :param oldrevid: Old revision id
    :param newrevid: New revision id
    :param newparents: New parent revision ids
    """
    repository = wt.branch.repository
    if merge_type is None:
        from bzrlib.merge import Merge3Merger
        merge_type = Merge3Merger
    oldrev = wt.branch.repository.get_revision(oldrevid)
    # Make sure there are no conflicts or pending merges/changes 
    # in the working tree
    complete_revert(wt, [newparents[0]])
    assert not wt.changes_from(wt.basis_tree()).has_changed(), "Changes in rev"

    oldtree = repository.revision_tree(oldrevid)
    write_active_rebase_revid(wt, oldrevid)
    merger = Merger(wt.branch, this_tree=wt)
    merger.set_other_revision(oldrevid, wt.branch)
    base_revid = replay_determine_base(repository.get_graph(),
                                       oldrevid, oldrev.parent_ids,
                                       newrevid, newparents)
    mutter('replaying %r as %r with base %r and new parents %r' %
           (oldrevid, newrevid, base_revid, newparents))
    merger.set_base_revision(base_revid, wt.branch)
    merger.merge_type = merge_type
    merger.do_merge()
    for newparent in newparents[1:]:
        wt.add_pending_merge(newparent)
    commit_rebase(wt, oldrev, newrevid)


def workingtree_replay(wt, map_ids=False, merge_type=None):
    """Returns a function that can replay revisions in wt.

    :param wt: Working tree in which to do the replays.
    :param map_ids: Whether to try to map between file ids (False for path-based merge)
    """
    def replay(repository, oldrevid, newrevid, newparents):
        assert wt.branch.repository == repository, "Different repository"
        return replay_delta_workingtree(wt, oldrevid, newrevid, newparents, 
                                        merge_type=merge_type)
    return replay


def write_active_rebase_revid(wt, revid):
    """Write the id of the revision that is currently being rebased. 

    :param wt: Working Tree that is being used for the rebase.
    :param revid: Revision id to write
    """
    if revid is None:
        revid = NULL_REVISION
    assert type(revid) == str
    wt._transport.put_bytes(REBASE_CURRENT_REVID_FILENAME, revid)


def read_active_rebase_revid(wt):
    """Read the id of the revision that is currently being rebased.

    :param wt: Working Tree that is being used for the rebase.
    :return: Id of the revision that is being rebased.
    """
    try:
        text = wt._transport.get_bytes(REBASE_CURRENT_REVID_FILENAME).rstrip("\n")
        if text == NULL_REVISION:
            return None
        return text
    except NoSuchFile:
        return None


def complete_revert(wt, newparents):
    """Simple helper that reverts to specified new parents and makes sure none 
    of the extra files are left around.

    :param wt: Working tree to use for rebase
    :param newparents: New parents of the working tree
    """
    newtree = wt.branch.repository.revision_tree(newparents[0])
    delta = wt.changes_from(newtree)
    wt.branch.generate_revision_history(newparents[0])
    wt.set_parent_ids(newparents[:1])
    for (f, _, _) in delta.added:
        abs_path = wt.abspath(f)
        if osutils.lexists(abs_path):
            if osutils.isdir(abs_path):
                osutils.rmtree(abs_path)
            else:
                os.unlink(abs_path)
    wt.revert(None, old_tree=newtree, backups=False)
    assert not wt.changes_from(wt.basis_tree()).has_changed(), "Rev changed"
    wt.set_parent_ids(newparents)


class ReplaySnapshotError(BzrError):
    """Raised when replaying a snapshot failed."""
    _fmt = """Replaying the snapshot failed: %(message)s."""

    def __init__(self, message):
        BzrError.__init__(self)
        self.message = message


class ReplayParentsInconsistent(BzrError):
    """Raised when parents were inconsistent."""
    _fmt = """Parents were inconsistent while replaying commit for file id %(fileid)s, revision %(revid)s."""

    def __init__(self, fileid, revid):
        BzrError.__init__(self)
        self.fileid = fileid
        self.revid = revid
