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

import os

from ... import config as _mod_config
from ... import osutils, ui
from ...bzr.generate_ids import gen_revision_id
from ...bzr.inventorytree import InventoryTreeChange
from ...errors import BzrError, NoCommonAncestor, UnknownFormatError, UnrelatedBranches
from ...graph import FrozenHeadsCache
from ...merge import Merger
from ...revision import NULL_REVISION
from ...trace import mutter
from ...transport import NoSuchFile
from ...tsort import topo_sort
from .maptree import MapTree, map_file_ids

REBASE_PLAN_FILENAME = "rebase-plan"
REBASE_CURRENT_REVID_FILENAME = "rebase-current"
REBASE_PLAN_VERSION = 1
REVPROP_REBASE_OF = "rebase-of"


class RebaseState:
    def has_plan(self):
        """Check whether there is a rebase plan present.

        :return: boolean
        """
        raise NotImplementedError(self.has_plan)

    def read_plan(self):
        """Read a rebase plan file.

        :return: Tuple with last revision info and replace map.
        """
        raise NotImplementedError(self.read_plan)

    def write_plan(self, replace_map):
        """Write a rebase plan file.

        :param replace_map: Replace map (old revid -> (new revid, new parents))
        """
        raise NotImplementedError(self.write_plan)

    def remove_plan(self):
        """Remove a rebase plan file."""
        raise NotImplementedError(self.remove_plan)

    def write_active_revid(self, revid):
        """Write the id of the revision that is currently being rebased.

        :param revid: Revision id to write
        """
        raise NotImplementedError(self.write_active_revid)

    def read_active_revid(self):
        """Read the id of the revision that is currently being rebased.

        :return: Id of the revision that is being rebased.
        """
        raise NotImplementedError(self.read_active_revid)


class RebaseState1(RebaseState):
    def __init__(self, wt):
        self.wt = wt
        self.transport = wt._transport

    def has_plan(self):
        """See `RebaseState`."""
        try:
            return self.transport.get_bytes(REBASE_PLAN_FILENAME) != b""
        except NoSuchFile:
            return False

    def read_plan(self):
        """See `RebaseState`."""
        text = self.transport.get_bytes(REBASE_PLAN_FILENAME)
        if text == b"":
            raise NoSuchFile(REBASE_PLAN_FILENAME)
        return unmarshall_rebase_plan(text)

    def write_plan(self, replace_map):
        """See `RebaseState`."""
        self.wt.update_feature_flags({b"rebase-v1": b"write-required"})
        content = marshall_rebase_plan(self.wt.branch.last_revision_info(), replace_map)
        assert isinstance(content, bytes)
        self.transport.put_bytes(REBASE_PLAN_FILENAME, content)

    def remove_plan(self):
        """See `RebaseState`."""
        self.wt.update_feature_flags({b"rebase-v1": None})
        self.transport.put_bytes(REBASE_PLAN_FILENAME, b"")

    def write_active_revid(self, revid):
        """See `RebaseState`."""
        if revid is None:
            revid = NULL_REVISION
        assert isinstance(revid, bytes)
        self.transport.put_bytes(REBASE_CURRENT_REVID_FILENAME, revid)

    def read_active_revid(self):
        """See `RebaseState`."""
        try:
            text = self.transport.get_bytes(REBASE_CURRENT_REVID_FILENAME).rstrip(b"\n")
            if text == NULL_REVISION:
                return None
            return text
        except NoSuchFile:
            return None


def marshall_rebase_plan(last_rev_info, replace_map):
    """Marshall a rebase plan.

    :param last_rev_info: Last revision info tuple.
    :param replace_map: Replace map (old revid -> (new revid, new parents))
    :return: string
    """
    ret = b"# Bazaar rebase plan %d\n" % REBASE_PLAN_VERSION
    ret += b"%d %s\n" % last_rev_info
    for oldrev in replace_map:
        (newrev, newparents) = replace_map[oldrev]
        ret += (
            b"%s %s" % (oldrev, newrev)
            + b"".join([b" %s" % p for p in newparents])
            + b"\n"
        )
    return ret


def unmarshall_rebase_plan(text):
    """Unmarshall a rebase plan.

    :param text: Text to parse
    :return: Tuple with last revision info, replace map.
    """
    lines = text.split(b"\n")
    # Make sure header is there
    if lines[0] != b"# Bazaar rebase plan %d" % REBASE_PLAN_VERSION:
        raise UnknownFormatError(lines[0])

    pts = lines[1].split(b" ", 1)
    last_revision_info = (int(pts[0]), pts[1])
    replace_map = {}
    for l in lines[2:]:
        if l == b"":
            # Skip empty lines
            continue
        pts = l.split(b" ")
        replace_map[pts[0]] = (pts[1], tuple(pts[2:]))
    return (last_revision_info, replace_map)


def regenerate_default_revid(repository, revid):
    """Generate a revision id for the rebase of an existing revision.

    :param repository: Repository in which the revision is present.
    :param revid: Revision id of the revision that is being rebased.
    :return: new revision id.
    """
    if revid == NULL_REVISION:
        return NULL_REVISION
    rev = repository.get_revision(revid)
    return gen_revision_id(rev.committer, rev.timestamp)


def generate_simple_plan(
    todo_set,
    start_revid,
    stop_revid,
    onto_revid,
    graph,
    generate_revid,
    skip_full_merged=False,
):
    """Create a simple rebase plan that replays history based
    on one revision being replayed on top of another.

    :param todo_set: A set of revisions to rebase. Only the revisions
        topologically between stop_revid and start_revid (inclusive) are
        rebased; other revisions are ignored (and references to them are
        preserved).
    :param start_revid: Id of revision at which to start replaying
    :param stop_revid: Id of revision until which to stop replaying
    :param onto_revid: Id of revision on top of which to replay
    :param graph: Graph object
    :param generate_revid: Function for generating new revision ids
    :param skip_full_merged: Skip revisions that merge already merged
                             revisions.

    :return: replace map
    """
    assert start_revid is None or start_revid in todo_set, (
        "invalid start revid({!r}), todo_set({!r})".format(start_revid, todo_set)
    )
    assert stop_revid is None or stop_revid in todo_set, "invalid stop_revid"
    replace_map = {}
    parent_map = graph.get_parent_map(todo_set)
    order = topo_sort(parent_map)
    if stop_revid is None:
        stop_revid = order[-1]
    if start_revid is None:
        # We need a common base.
        lca = graph.find_lca(stop_revid, onto_revid)
        if lca == {NULL_REVISION}:
            raise UnrelatedBranches()
        start_revid = order[0]
    todo = order[order.index(start_revid) : order.index(stop_revid) + 1]
    heads_cache = FrozenHeadsCache(graph)
    # XXX: The output replacemap'd parents should get looked up in some manner
    # by the heads cache? RBC 20080719
    for oldrevid in todo:
        oldparents = parent_map[oldrevid]
        assert isinstance(oldparents, tuple), "not tuple: {!r}".format(oldparents)
        parents = []
        # Left parent:
        if heads_cache.heads((oldparents[0], onto_revid)) == {onto_revid}:
            parents.append(onto_revid)
        elif oldparents[0] in replace_map:
            parents.append(replace_map[oldparents[0]][0])
        else:
            parents.append(onto_revid)
            parents.append(oldparents[0])
        # Other parents:
        if len(oldparents) > 1:
            additional_parents = heads_cache.heads(oldparents[1:])
            for oldparent in oldparents[1:]:
                if oldparent in additional_parents:
                    if heads_cache.heads((oldparent, onto_revid)) == {onto_revid}:
                        pass
                    elif oldparent in replace_map:
                        newparent = replace_map[oldparent][0]
                        if parents[0] == onto_revid:
                            parents[0] = newparent
                        else:
                            parents.append(newparent)
                    else:
                        parents.append(oldparent)
            if len(parents) == 1 and skip_full_merged:
                continue
        parents = tuple(parents)
        newrevid = generate_revid(oldrevid, parents)
        assert newrevid != oldrevid, "old and newrevid equal ({!r})".format(newrevid)
        assert isinstance(parents, tuple), "parents not tuple: {!r}".format(parents)
        replace_map[oldrevid] = (newrevid, parents)
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
        if r not in children:
            children[r] = []
        if ps is None:  # Ghost
            continue
        parent_map[r] = ps
        if r not in children:
            children[r] = []
        for p in ps:
            if p not in children:
                children[p] = []
            children[p].append(r)

    parent_map.update(
        graph.get_parent_map(filter(lambda x: x not in parent_map, renames.values()))
    )

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
            pb.update("determining dependencies", i, total)
            # Add entry for them in replace_map
            for c in children[r]:
                if c in renames:
                    continue
                if c in replace_map:
                    parents = replace_map[c][1]
                else:
                    parents = parent_map[c]
                assert isinstance(parents, tuple), (
                    "Expected tuple of parents, got: {!r}".format(parents)
                )
                # replace r in parents with replace_map[r][0]
                if replace_map[r][0] not in parents:
                    parents = list(parents)
                    parents[parents.index(r)] = replace_map[r][0]
                    parents = tuple(parents)
                replace_map[c] = (generate_revid(c, tuple(parents)), tuple(parents))
                if replace_map[c][0] == c:
                    del replace_map[c]
                elif c not in processed:
                    todo.append(c)
    finally:
        pb.finished()

    # Remove items from the map that already exist
    for revid in renames:
        if revid in replace_map:
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


def rebase(repository, replace_map, revision_rewriter):
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
            pb.update("rebase revisions", i, len(todo))
            (newrevid, newparents) = replace_map[revid]
            assert isinstance(newparents, tuple), "Expected tuple for {!r}".format(newparents)
            if repository.has_revision(newrevid):
                # Was already converted, no need to worry about it again
                continue
            revision_rewriter(revid, newrevid, newparents)
    finally:
        pb.finished()


def wrap_iter_changes(old_iter_changes, map_tree):
    for change in old_iter_changes:
        if change.parent_id[0] is not None:
            old_parent = map_tree.new_id(change.parent_id[0])
        else:
            old_parent = change.parent_id[0]
        if change.parent_id[1] is not None:
            new_parent = map_tree.new_id(change.parent_id[1])
        else:
            new_parent = change.parent_id[1]
        yield InventoryTreeChange(
            map_tree.new_id(change.file_id),
            change.path,
            change.changed_content,
            change.versioned,
            (old_parent, new_parent),
            change.name,
            change.kind,
            change.executable,
        )


class CommitBuilderRevisionRewriter:
    """Revision rewriter that use commit builder.

    :ivar repository: Repository in which the revision is present.
    """

    def __init__(self, repository, map_ids=True):
        self.repository = repository
        self.map_ids = map_ids

    def _get_present_revisions(self, revids):
        return tuple([p for p in revids if self.repository.has_revision(p)])

    def __call__(self, oldrevid, newrevid, new_parents):
        """Replay a commit by simply commiting the same snapshot with different
        parents.

        :param oldrevid: Revision id of the revision to copy.
        :param newrevid: Revision id of the revision to create.
        :param new_parents: Revision ids of the new parent revisions.
        """
        assert isinstance(new_parents, tuple), (
            "CommitBuilderRevisionRewriter: Expected tuple for {!r}".format(new_parents)
        )
        mutter(
            "creating copy %r of %r with new parents %r",
            newrevid,
            oldrevid,
            new_parents,
        )
        oldrev = self.repository.get_revision(oldrevid)

        revprops = dict(oldrev.properties)
        revprops[REVPROP_REBASE_OF] = oldrevid.decode("utf-8")

        # Check what new_ie.file_id should be
        # use old and new parent trees to generate new_id map
        nonghost_oldparents = self._get_present_revisions(oldrev.parent_ids)
        nonghost_newparents = self._get_present_revisions(new_parents)
        oldtree = self.repository.revision_tree(oldrevid)
        if self.map_ids:
            fileid_map = map_file_ids(
                self.repository, nonghost_oldparents, nonghost_newparents
            )
            mappedtree = MapTree(oldtree, fileid_map)
        else:
            mappedtree = oldtree

        try:
            old_base = nonghost_oldparents[0]
        except IndexError:
            old_base = NULL_REVISION
        try:
            new_base = new_parents[0]
        except IndexError:
            new_base = NULL_REVISION
        old_base_tree = self.repository.revision_tree(old_base)
        old_iter_changes = oldtree.iter_changes(old_base_tree)
        iter_changes = wrap_iter_changes(old_iter_changes, mappedtree)
        builder = self.repository.get_commit_builder(
            branch=None,
            parents=new_parents,
            committer=oldrev.committer,
            timestamp=oldrev.timestamp,
            timezone=oldrev.timezone,
            revprops=revprops,
            revision_id=newrevid,
            config_stack=_mod_config.GlobalStack(),
        )
        try:
            for _relpath, _fs_hash in builder.record_iter_changes(
                mappedtree, new_base, iter_changes
            ):
                pass
            builder.finish_inventory()
            return builder.commit(oldrev.message)
        except:
            builder.abort()
            raise


class WorkingTreeRevisionRewriter:
    def __init__(self, wt, state, merge_type=None):
        """:param wt: Working tree in which to do the replays."""
        self.wt = wt
        self.graph = self.wt.branch.repository.get_graph()
        self.state = state
        self.merge_type = merge_type

    def __call__(self, oldrevid, newrevid, newparents):
        """Replay a commit in a working tree, with a different base.

        :param oldrevid: Old revision id
        :param newrevid: New revision id
        :param newparents: New parent revision ids
        """
        repository = self.wt.branch.repository
        if self.merge_type is None:
            from ...merge import Merge3Merger

            merge_type = Merge3Merger
        else:
            merge_type = self.merge_type
        oldrev = self.wt.branch.repository.get_revision(oldrevid)
        # Make sure there are no conflicts or pending merges/changes
        # in the working tree
        complete_revert(self.wt, [newparents[0]])
        assert not self.wt.changes_from(self.wt.basis_tree()).has_changed(), (
            "Changes in rev"
        )

        repository.revision_tree(oldrevid)
        self.state.write_active_revid(oldrevid)
        merger = Merger(self.wt.branch, this_tree=self.wt)
        merger.set_other_revision(oldrevid, self.wt.branch)
        base_revid = self.determine_base(
            oldrevid, oldrev.parent_ids, newrevid, newparents
        )
        mutter(
            "replaying {!r} as {!r} with base {!r} and new parents {!r}".format(oldrevid, newrevid, base_revid, newparents)
        )
        merger.set_base_revision(base_revid, self.wt.branch)
        merger.merge_type = merge_type
        merger.do_merge()
        for newparent in newparents[1:]:
            self.wt.add_pending_merge(newparent)
        self.commit_rebase(oldrev, newrevid)
        self.state.write_active_revid(None)

    def determine_base(self, oldrevid, oldparents, newrevid, newparents):
        """Determine the base for replaying a revision using merge.

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

        # In case the rhs parent(s) of the origin revision has already been
        # merged in the new branch, use diff between rhs parent and diff from
        # original revision
        if len(newparents) == 1:
            # FIXME: Find oldparents entry that matches newparents[0]
            # and return it
            return oldparents[1]

        try:
            return self.graph.find_unique_lca(*[oldparents[0], newparents[1]])
        except NoCommonAncestor:
            return oldparents[0]

    def commit_rebase(self, oldrev, newrevid):
        """Commit a rebase.

        :param oldrev: Revision info of new revision to commit.
        :param newrevid: New revision id.
        """
        assert oldrev.revision_id != newrevid, "Invalid revid {!r}".format(newrevid)
        revprops = dict(oldrev.properties)
        revprops[REVPROP_REBASE_OF] = oldrev.revision_id.decode("utf-8")
        committer = self.wt.branch.get_config().username()
        authors = oldrev.get_apparent_authors()
        if oldrev.committer == committer:
            # No need to explicitly record the authors if the original
            # committer is rebasing.
            if [oldrev.committer] == authors:
                authors = None
        else:
            if oldrev.committer not in authors:
                authors.append(oldrev.committer)
        if "author" in revprops:
            del revprops["author"]
        if "authors" in revprops:
            del revprops["authors"]
        self.wt.commit(
            message=oldrev.message,
            timestamp=oldrev.timestamp,
            timezone=oldrev.timezone,
            revprops=revprops,
            rev_id=newrevid,
            committer=committer,
            authors=authors,
        )


def complete_revert(wt, newparents):
    """Simple helper that reverts to specified new parents and makes sure none
    of the extra files are left around.

    :param wt: Working tree to use for rebase
    :param newparents: New parents of the working tree
    """
    newtree = wt.branch.repository.revision_tree(newparents[0])
    delta = wt.changes_from(newtree)
    wt.branch.generate_revision_history(newparents[0])
    wt.set_parent_ids([r for r in newparents[:1] if r != NULL_REVISION])
    for change in delta.added:
        abs_path = wt.abspath(change.path[1])
        if osutils.lexists(abs_path):
            if osutils.isdir(abs_path):
                osutils.rmtree(abs_path)
            else:
                os.unlink(abs_path)
    wt.revert(None, old_tree=newtree, backups=False)
    assert not wt.changes_from(wt.basis_tree()).has_changed(), "Rev changed"
    wt.set_parent_ids([r for r in newparents if r != NULL_REVISION])


class ReplaySnapshotError(BzrError):
    """Raised when replaying a snapshot failed."""

    _fmt = """Replaying the snapshot failed: %(msg)s."""

    def __init__(self, msg):
        BzrError.__init__(self)
        self.msg = msg
