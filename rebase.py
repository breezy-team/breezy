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

from bzrlib.config import Config
from bzrlib.errors import UnknownFormatError, NoSuchFile, BzrError
from bzrlib.generate_ids import gen_revision_id
from bzrlib.trace import mutter
import bzrlib.ui as ui

REBASE_PLAN_FILENAME = 'rebase-plan'
REBASE_PLAN_VERSION = 1

def rebase_plan_exists(wt):
    """Check whether there is a rebase plan present.

    :param wt: Working tree for which to check.
    :return: boolean
    """
    try:
        return wt._control_files.get(REBASE_PLAN_FILENAME).read() != ''
    except NoSuchFile:
        return False


def read_rebase_plan(wt):
    """Read a rebase plan file.

    :param wt: Working Tree for which to write the plan.
    :return: Tuple with last revision info and replace map.
    """
    text = wt._control_files.get(REBASE_PLAN_FILENAME).read()
    if text == '':
        raise NoSuchFile(REBASE_PLAN_FILENAME)
    return unmarshall_rebase_plan(text)


def write_rebase_plan(wt, replace_map):
    """Write a rebase plan file.

    :param wt: Working Tree for which to write the plan.
    :param replace_map: Replace map (old revid -> (new revid, new parents))
    """
    wt._control_files.put_utf8(REBASE_PLAN_FILENAME, 
            marshall_rebase_plan(wt.branch.last_revision_info(), replace_map))


def remove_rebase_plan(wt):
    """Remove a rebase plan file.

    :param wt: Working Tree for which to remove the plan.
    """
    wt._control_files.put_utf8(REBASE_PLAN_FILENAME, '')


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
        replace_map[pts[0]] = (pts[1], pts[2:])
    return (last_revision_info, replace_map)


def regenerate_default_revid(rev):
    return gen_revision_id(rev.committer, rev.timestamp)


def generate_simple_plan(repository, history, start_revid, onto_revid, 
                         generate_revid=regenerate_default_revid):
    """Create a simple rebase plan that replays history based 
    on one revision being replayed on top of another.

    :param repository: Repository
    :param history: Revision history
    :param start_revid: Id of revision at which to start replaying
    :param onto_revid: Id of revision on top of which to replay
    :param generate_revid: Function for generating new revision ids

    :return: replace map
    """
    assert start_revid in history
    assert repository.has_revision(start_revid)
    assert repository.has_revision(onto_revid)
    replace_map = {}
    i = history.index(start_revid)
    new_parent = onto_revid
    for oldrevid in history[i:]: 
        rev = repository.get_revision(oldrevid)
        parents = rev.parent_ids
        assert len(parents) == 0 or \
                parents[0] == history[history.index(oldrevid)-1]
        parents[0] = new_parent
        newrevid = generate_revid(rev)
        assert newrevid != oldrevid
        replace_map[oldrevid] = (newrevid, parents)
        new_parent = newrevid
    return replace_map


def generate_transpose_plan(repository, graph, renames, 
        generate_revid=regenerate_default_revid):
    """Create a rebase plan that replaces the bottom of 
    a revision graph.

    :param repository: Repository
    :param graph: Revision graph in which to operate
    :param renames: Renames of revision
    :param generate_revid: Function for creating new revision ids
    """
    replace_map = {}
    todo = []
    for r in renames:
        replace_map[r] = (renames[r], 
                          repository.revision_parents(renames[r]))
        todo.append(r)

    def find_revision_children(revid):
        for x in graph: 
            if revid in graph[x]: 
                yield x

    while len(todo) > 0:
        r = todo.pop()
        # Find children of r in graph
        children = list(find_revision_children(r))
        # Add entry for them in replace_map
        for c in children:
            rev = repository.get_revision(c)
            if replace_map.has_key(c):
                parents = replace_map[c][1]
            else:
                parents = rev.parent_ids
            # replace r in parents with replace_map[r][0]
            parents[parents.index(r)] = replace_map[r][0]
            replace_map[c] = (generate_revid(rev), parents)
            assert replace_map[c][0] != rev.revision_id
        # Add them to todo[]
        todo.extend(children)

    return replace_map


def rebase(repository, replace_map, replay_fn):
    """Rebase a working tree according to the specified map.

    :param repository: Repository that contains the revisions
    :param replace_map: Dictionary with revisions to (optionally) rewrite
    :param merge_fn: Function for replaying a revision
    """
    todo = []
    for revid in replace_map:
        if not repository.has_revision(replace_map[revid][0]):
            todo.append(revid)
    dependencies = {}

    # Figure out the dependencies
    for revid in todo:
        possible = True
        for p in replace_map[revid][1]:
            if repository.has_revision(p):
                continue
            possible = False
            if not dependencies.has_key(p):
                dependencies[p] = []
            dependencies[p].append(revid)

    pb = ui.ui_factory.nested_progress_bar()
    i = 0
    try:
        while len(todo) > 0:
            pb.update('rebase revisions', i, len(replace_map))
            i += 1
            revid = todo.pop()
            (newrevid, newparents) = replace_map[revid]
            if not all(map(repository.has_revision, newparents)):
                # Not all parents present yet, avoid for now
                continue
            if repository.has_revision(newrevid):
                # Was already converted, no need to worry about it again
                continue
            replay_fn(repository, revid, newrevid, newparents)
            assert repository.has_revision(newrevid)
            assert repository.revision_parents(newrevid) == newparents
            if dependencies.has_key(newrevid):
                todo.extend(dependencies[newrevid])
                del dependencies[newrevid]
    finally:
        pb.finished()
        
    assert all(map(repository.has_revision, [replace_map[r][0] for r in replace_map]))
     

class MapTree:
    def __init__(self, oldtree, old_parents, new_parents):
        self.map = {}
        for (oldp, newp) in zip(old_parents, new_parents):
            oldinv = repository.get_revision_inventory(oldp)
            newinv = repository.get_revision_inventory(newp)
            for path, ie in oldinv.iter_entries():
                if newinv.has_filename(path):
                    self.map[ie.file_id] = newinv.path2id(path)
        self.oldtree = oldtree

    def old_id(self, file_id):
        for x in self.map:
            if self.map[x] == file_id:
                return x
        return file_id

    def new_id(self, file_id):
        try:
            return new_id[file_id]
        except KeyError:
            return file_id

    def get_file_sha1(self, file_id, path=None):
        return self.oldtree.get_file_sha1(file_id=self.old_id(file_id), 
                                          path=path)

    def get_file(self, file_id):
        return self.oldtree.get_file(self.old_id(file_id=file_id))

    def is_executable(self, file_id, path=None):
        return self.oldtree.is_executable(self.old_id(file_id=file_id), 
                                          path=path)

def replay_snapshot(repository, oldrevid, newrevid, new_parents):
    """Replay a commit by simply commiting the same snapshot with different parents.

    :param repository: Repository in which the revision is present.
    :param oldrevid: Revision id of the revision to copy.
    :param newrevid: Revision id of the revision to create.
    :param new_parents: Revision ids of the new parent revisions.
    """
    assert isinstance(new_parents, list)
    mutter('creating copy %r of %r with new parents %r' % (newrevid, oldrevid, new_parents))
    oldrev = repository.get_revision(oldrevid)

    revprops = dict(oldrev.properties)
    revprops['rebase-of'] = oldrevid

    builder = repository.get_commit_builder(branch=None, parents=new_parents, 
                                  config=Config(),
                                  committer=oldrev.committer,
                                  timestamp=oldrev.timestamp,
                                  timezone=oldrev.timezone,
                                  revprops=revprops,
                                  revision_id=newrevid)

    # Check what new_ie.file_id should be
    # use old and new parent inventories to generate new_id map
    oldtree = MapTree(repository.revision_tree(oldrevid), 
                      oldrev.parent_ids, new_parents)
    oldinv = repository.get_revision_inventory(oldrevid)
    total = len(oldinv)
    pb = ui.ui_factory.nested_progress_bar()
    i = 0
    try:
        transact = repository.get_transaction()
        for path, ie in oldinv.iter_entries():
            pb.update('upgrading file', i, total)
            i += 1
            new_ie = ie.copy()
            if new_ie.revision == oldrevid:
                new_ie.revision = None
            new_ie.file_id = oldtree.new_id(new_ie.file_id)
            new_ie.parent_id = oldtree.new_id(new_ie.parent_id)
            builder.record_entry_contents(new_ie, 
                   map(repository.get_revision_inventory, new_parents), 
                   path, oldtree)
    finally:
        pb.finished()

    builder.finish_inventory()
    return builder.commit(oldrev.message)


def replay_delta_workingtree(wt, oldrevid, newrevid, newparents, map_ids=False,
        merge_type=None):
    """Replay a commit in a working tree, with a different base.

    :param wt: Working tree in which to do the replays.
    :param oldrevid: Old revision id
    :param newrevid: New revision id
    :param newparents: New parent revision ids
    :param map_ids: Whether to map file ids from the rebased revision using 
        the old and new parent tree file ids.
    """
    repository = wt.branch.repository
    if merge_type is None:
        from bzrlib.merge import Merge3Merger
        merge_type = Merge3Merger
    oldrev = wt.branch.repository.get_revision(oldrevid)
    # Make sure there are no conflicts or pending merges/changes 
    # in the working tree
    if wt.changes_from(wt.basis_tree()).has_changed():
        raise BzrError("Working tree has uncommitted changes.")
    wt.branch.generate_revision_history(newparents[0])
    wt.set_parent_ids(newparents)
    wt.revert([], backups=False)
    assert not wt.changes_from(wt.basis_tree()).has_changed()

    oldtree = repository.revision_tree(oldrevid)
    basetree = repository.revision_tree(oldrev.parent_ids[0])
    if map_ids:
        oldtree = MapTree(oldtree, oldrev.parent_ids, new_parents)
        basetree = MapTree(basetree, oldrev.parent_ids, new_parents)

    merge = merge_type(working_tree=wt, this_tree=wt, 
            base_tree=basetree,
            other_tree=oldtree)

    # commit
    revprops = dict(oldrev.properties)
    revprops['rebase-of'] = oldrevid
    wt.commit(message=oldrev.message, timestamp=oldrev.timestamp, timezone=oldrev.timezone,
              revprops=revprops, rev_id=newrevid)


def workingtree_replay(wt, map_ids=False):
    """Returns a function that can replay revisions in wt.

    :param wt: Working tree in which to do the replays.
    :param map_ids: Whether to try to map between file ids (False for path-based merge)
    """
    def replay(repository, oldrevid, newrevid, newparents):
        assert wt.branch.repository == repository
        return replay_delta_workingtree(wt, oldrevid, newrevid, newparents)
    return replay

class MergeConflicted(BzrError):
    _fmt = "Conflict during merge"
