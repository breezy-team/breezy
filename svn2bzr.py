#!/usr/bin/env python
#
# Copyright (C) 2005 by Canonical Ltd
#
# Written by Gustavo Niemeyer <gustavo@niemeyer.net>
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
#
import optparse
import tempfile
import logging
import marshal
import sys, os
import shutil
import anydbm
import time
import bz2
import re

logger = logging.getLogger("bzr")
logger.addHandler(logging.FileHandler("/dev/null"))

from bzrlib.branch import Branch
import bzrlib.trace

try:
    from bzrlib.branch import copy_branch
except ImportError:
    from bzrlib.clone import copy_branch


VERSION = "0.5"


# For compatibility with previous code.
if not hasattr(Branch, "initialize"):
    Branch.initialize = staticmethod(lambda path: Branch(path, init=True))
    Branch.open = staticmethod(lambda path: Branch(path))


def get_logger():
    if hasattr(get_logger, "initialized"):
        logger = logging.getLogger("svn2bzr")
    else:
        get_logger.initialized = True
        class Formatter(logging.Formatter):
            def format(self, record):
                if record.levelno != logging.INFO:
                    record.prefix = record.levelname.lower()+": "
                else:
                    record.prefix = ""
                return logging.Formatter.format(self, record)
        formatter = Formatter("%(prefix)s%(message)s")
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        #logger = logging.getLogger("bzr")
        #logger.addHandler(handler)
        #logger.setLevel(logging.ERROR)
        logger = logging.getLogger("svn2bzr")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


class Error(Exception): pass
class FormatVersionError(Error): pass
class IncrementalDumpError(Error): pass


class BranchCreator(object):

    def __init__(self, dump, root=None, prefix=None, log=None):
        self._dump = dump
        self._root = os.path.realpath(root)
        if prefix:
            self._prefix = prefix.strip("/")
            self._prefix_dir = self._prefix+"/"
        else:
            self._prefix = None
            self._prefix_dir = None
        self._revisions = {}
        self._changed = {}
        self._filter = []
        self._log = log or get_logger()

        self._do_cache = {}

    def _do(self, branch, action, path):
        last = self._do_cache.get(branch)
        if last and action == last[0]:
            last[1].append(path)
        else:
            if last:
                self._do_now(branch, *last)
            self._do_cache[branch] = (action, [path])

    def _do_now(self, branch, action, paths):
        if action == "add":
            branch.add(paths)
        elif action == "remove":
            branch.remove(paths)
        else:
            raise RuntimeError, "Unknown action: %r" % action

    def _new_branch(self, branch):
        # Ugly, but let's wait until that API stabilizes. Right
        # now branch.working_tree() will open the branch again.
        branch.__wt = branch.working_tree()

    def _remove_branch(self, branch):
        raise NotImplementedError
            
    def _get_branch(self, path):
        raise NotImplementedError

    def _get_all_branches(self):
        raise NotImplementedError

    def _get_branch_path(self, path):
        path = self.unprefix(path)
        if self.is_good(path):
            branch = self._get_branch(path)
            if branch:
                abspath = os.path.join(self._root, path)
                return branch, branch.__wt.relpath(abspath)
        return None, None

    def _get_tree(self, branch, revision=None):
        if revision is None:
            return branch.__wt
        else:
            revno = self._revisions[revision][branch]
            revid = branch.get_rev_id(revno)
            return branch.revision_tree(revid)

    def add_filter(self, include, regexp):
        self._filter.append((include, re.compile(regexp)))

    def is_good(self, path):
        for include, pattern in self._filter:
            if pattern.match(path):
                return include
        return True

    def unprefix(self, path):
        if not self._prefix:
            return path
        elif path == self._prefix:
            return ""
        elif path.startswith(self._prefix):
            return path[len(self._prefix)+1:]
        else:
            return None


    def add_file(self, path, content):
        branch, path_branch = self._get_branch_path(path)
        if branch:
            abspath = branch.__wt.abspath(path_branch)
            self._log.debug("Adding file: %s" % abspath)
            open(abspath, "w").write(content)
            self._do(branch, "add", path_branch)
            self._changed[branch] = True

    def change_file(self, path, content):
        branch, path_branch = self._get_branch_path(path)
        if branch:
            abspath = branch.__wt.abspath(path_branch)
            self._log.debug("Changing file: %s" % abspath)
            open(abspath, "w").write(content)
            self._changed[branch] = True

    def copy_file(self, orig_path, orig_revno, dest_path):
        dest_branch, dest_path_branch = self._get_branch_path(dest_path)
        if dest_branch:
            orig_entry = self._dump.get_entry(orig_revno, orig_path)
            orig_content = self._dump.get_entry_content(orig_entry)
            abspath = dest_branch.__wt.abspath(dest_path_branch)
            self._log.debug("Copying file: %s at %d to %s" %
                            (orig_path, orig_revno, abspath))
            open(abspath, "w").write(orig_content)
            self._do(dest_branch, "add", dest_path_branch)
            self._changed[dest_branch] = True

    def add_dir(self, path):
        branch, path_branch = self._get_branch_path(path)
        # The path test below checks if we got an empty path,
        # which happens when adding the self._prefix directory itself,
        # and shouldn't be considered since creating that directory
        # must have been done by _get_branch().
        if branch and path_branch:
            # Due to filtering, the directory may be added
            # without adding parent directories.
            abspath = branch.__wt.abspath(path_branch)
            self._log.debug("Adding dir: %s" % abspath)
            if os.path.isdir(os.path.dirname(abspath)):
                os.mkdir(abspath)
                self._do(branch, "add", path_branch)
            else:
                path_parts = path_branch.split('/')
                dir = branch.base
                for part in path_parts:
                    dir = "%s/%s" % (dir, part)
                    if not os.path.isdir(dir):
                        os.mkdir(dir)
                        self._do(branch, "add",
                                 branch.__wt.relpath(dir))
            self._changed[branch] = True

    def copy_dir(self, orig_path, orig_revno, dest_path):
        # Inside that method we cannot assume that dest_branch
        # is a valid branch, since we may be interested just in
        # part of the copy being made, for which a branch does
        # exist.
        #
        # To better understand what each path means, let's assume that
        # a copy of "trunk/foo" is being made to "branches/mine/foo",
        # "trunk" and "branches/mine" are different branches", and that
        # "trunk/foo/bar" exists and is being copied during the current
        # iteration.
        #
        # orig_path = "trunk/foo"
        # dest_path = "branches/mine/foo"
        # dest_path_branch = "foo"
        # path = "trunk/foo/bar"
        # tail = "bar"
        # copy_dest_path = "branches/mine/foo/bar"
        #
        # Got it? :-)
        #
        dest_branch, dest_path_branch = self._get_branch_path(dest_path)
        entries = self._dump.get_dir_tree(orig_revno, orig_path).items()
        entries.sort()
        changed = False
        for path, entry in entries:
            tail = path[len(orig_path)+1:]
            copy_dest_path = os.path.join(dest_path, tail)
            node_kind = entry["node-kind"]
            if node_kind == "file":
                content = self._dump.get_entry_content(entry)
                self.add_file(copy_dest_path, content)
            elif node_kind == "dir":
                self.add_dir(copy_dest_path)

    def copy(self, orig_path, orig_revno, dest_path):
        orig_entry = self._dump.get_entry(orig_revno, orig_path)
        if orig_entry["node-kind"] == "dir":
            self.copy_dir(orig_path, orig_revno, dest_path)
        else:
            self.copy_file(orig_path, orig_revno, dest_path)

    def move(self, orig_path, orig_revno, dest_path):
        orig_branch, orig_path_branch = self._get_branch_path(orig_path)
        dest_branch, dest_path_branch = self._get_branch_path(dest_path)
        if not dest_branch or orig_branch != dest_branch:
            self.remove(orig_path)
            self.copy(orig_path, orig_revno, dest_path)
        else:
            orig_abspath = orig_branch.__wt.abspath(orig_path_branch)
            if not os.path.exists(orig_abspath):
                # Was previously removed, as usual in svn.
                orig_branch.revert([orig_path_branch])
            self._log.debug("Moving: %s to %s" %
                            (orig_abspath,
                             dest_branch.__wt.abspath(dest_path_branch)))
            if (os.path.dirname(orig_path_branch) ==
                os.path.dirname(dest_path_branch)):
                orig_branch.rename_one(orig_path_branch,
                                       dest_path_branch)
            else:
                orig_branch.move([orig_path_branch], dest_path_branch)
            self._changed[orig_branch] = True

    def remove(self, path):
        branch, path_branch = self._get_branch_path(path)
        if branch:
            abspath = branch.__wt.abspath(path_branch)
            if not path_branch:
                # Do we want to remove the branch or its content?
                self._log.debug("Removing branch: %s" % abspath)
                self._remove_branch(branch)
            elif os.path.exists(abspath):
                self._do(branch, "remove", path_branch)
                if os.path.isdir(abspath):
                    self._log.debug("Removing dir: %s" % abspath)
                    shutil.rmtree(abspath)
                    # If the directory parent is filtered, no one is
                    # taking care of it, so remove it as well.
                    abspath = os.path.dirname(abspath)
                    while abspath != branch.base:
                        relpath = abspath[len(branch.base)+1:]
                        if self.is_good(relpath):
                            break
                        try:
                            os.rmdir(abspath)
                            self._do(branch, "remove", relpath)
                        except OSError:
                            break
                elif os.path.isfile(abspath):
                    self._log.debug("Removing file: %s" % abspath)
                    os.unlink(abspath)
                self._changed[branch] = True

    def commit(self, revno, message, committer, timestamp):
        if self._changed:
            self._log.info("Committing revision %d" % revno)
            for branch in self._changed:
                if branch in self._do_cache:
                    self._do_now(branch, *self._do_cache[branch])
                branch.commit(message, committer=committer,
                              timestamp=timestamp, verbose=False)
            self._do_cache.clear()
        else:
            self._log.info("Nothing changed in revision %d" % revno)
        self._revisions[revno] = revs = {}
        for branch in self._get_all_branches():
            revs[branch] = branch.revno()
        self._changed.clear()

    def run(self):

        revision = None
        revno = None

        def commit():
            # Parse timestamps like 2005-09-23T17:52:33.719737Z
            time_tokens = revision.prop["svn:date"].split(".")
            parsed_time = time.strptime(time_tokens[0],
                                        "%Y-%m-%dT%H:%M:%S")
            timestamp = time.mktime(parsed_time)
            timestamp += float(time_tokens[1][:-1])

            self.commit(revno, revision.prop.get("svn:log", ""),
                        committer=revision.prop.get("svn:author"),
                        timestamp=timestamp)

        deleted = {}

        for entry in self._dump:
            
            if "revision-number" in entry:

                if revision is not None and revno != 0:
                    commit()

                revision = entry
                revno = revision["revision-number"]

                deleted.clear()

            elif "node-path" in entry:

                node_path = entry["node-path"]

                if self.unprefix(node_path) is None:
                    continue

                node_action = entry["node-action"]
                node_kind = entry.get("node-kind")
                
                if node_kind not in (None, "file", "dir"):
                    raise Error, "Unknown entry kind: %s" % node_kind
                if node_action not in ("add", "delete", "change", "replace"):
                    raise Error, "Unknown action: %s" % node_action

                if node_action == "delete":
                    self.remove(node_path)
                    deleted[node_path] = True

                elif node_action == "add" or node_action == "replace":

                    if node_action == "replace":
                        self.remove(node_path)

                    if "node-copyfrom-path" in entry:
                        copy_path = entry["node-copyfrom-path"]
                        copy_revno = entry["node-copyfrom-rev"]

                        if copy_path in deleted and copy_revno == revno-1:
                            self.move(copy_path, copy_revno, node_path)
                        elif node_kind == "file":
                            self.copy_file(copy_path, copy_revno, node_path)
                        else:
                            self.copy_dir(copy_path, copy_revno, node_path)

                    elif node_kind == "file":
                        content = self._dump.get_entry_content(entry)
                        self.add_file(node_path, content)

                    elif node_kind == "dir":
                        self.add_dir(node_path)

                elif node_action == "change":

                    if (node_kind == "file" and
                        entry.content_pos != entry.change_from.content_pos):
                        content = self._dump.get_entry_content(entry)
                        self.change_file(node_path, content)

        if revision is not None:
            commit()


class SingleBranchCreator(BranchCreator):

    def __init__(self, dump, root, prefix=None, log=None):
        BranchCreator.__init__(self, dump, root, prefix, log)
        self._branch = None

    def _remove_branch(self, branch):
        self._branch = None
        shutil.rmtree(self._root)

    def _get_branch(self, path):
        if not self._branch:
            self._branch = Branch.initialize(self._root)
            self._new_branch(self._branch)
        return self._branch

    def _get_all_branches(self):
        if self._branch is None:
            return []
        else:
            return [self._branch]


class DynamicBranchCreator(BranchCreator):

    def __init__(self, dump, root, prefix=None, log=None):
        BranchCreator.__init__(self, dump, root, prefix, log)
        self._branches = {}

    def _remove_branch(self, branch):
        shutil.rmtree(branch.base)
        del self._branches[branch.base[len(self._root)+1:]]

    def _want_branch(self, path):
        raise NotImplemented

    def _get_branch(self, path):
        for branch_path in self._branches:
            if path == branch_path or path.startswith(branch_path+"/"):
                return self._branches[branch_path]

    def _get_all_branches(self):
        return self._branches.values()

    def add_dir(self, path):
        branch, path_branch = self._get_branch_path(path)
        unpref_path = self.unprefix(path)
        if not branch:
            if self.is_good(unpref_path) and self._want_branch(unpref_path):
                branch_path = os.path.join(self._root, unpref_path)
                os.makedirs(branch_path)
                branch = Branch.initialize(branch_path)
                self._branches[unpref_path] = branch
                self._new_branch(branch)
        else:
            BranchCreator.add_dir(self, path)
 
    def copy_dir(self, orig_path, orig_revno, dest_path):
        # unpref_dest_path can't be None because it was
        # already filtered in run()
        unpref_orig_path = self.unprefix(orig_path)
        unpref_dest_path = self.unprefix(dest_path)
        orig_abspath = os.path.join(self._root, unpref_orig_path)
        if (unpref_orig_path is None or
            not os.path.isdir(os.path.join(orig_abspath, ".bzr")) or
            self._get_branch(unpref_dest_path)):

            # Normal copy
            BranchCreator.copy_dir(self, orig_path, orig_revno,
                                          dest_path)

        elif self.is_good(unpref_dest_path):

            # Create new branch
            dest_abspath = os.path.join(self._root, unpref_dest_path)
            orig_branch = self._get_branch(unpref_orig_path)
            revno = self._revisions[orig_revno][orig_branch]
            os.makedirs(dest_abspath)
            revid = orig_branch.get_rev_id(revno)
            copy_branch(orig_branch, dest_abspath, revid)
            branch = Branch.open(dest_abspath)
            self._branches[unpref_dest_path] = branch
            self._new_branch(branch)

    def remove(self, path):
        unpref_path = self.unprefix(path)
        if not self._get_branch(unpref_path):
            abspath = os.path.join(self._root, unpref_path)
            if os.path.isdir(abspath):
                shutil.rmtree(abspath)
                path += "/"
                for branch_path in self._branches.keys():
                    if branch_path.startswith(path):
                        del self._branches[branch_path]
        else:
            BranchCreator.remove(self, path)
        

class TrunkBranchCreator(DynamicBranchCreator):

    def _want_branch(self, path):
        return path not in ("tags", "branches")


class DumpEntry(dict):
    """
    An entry in a dump file.
    """

    __slots__ = ["prop", "content_pos", "content_len",
                 "copy_from", "change_from"]

    def __init__(self):
        self.prop = {}
        self.content_pos = 0
        self.content_len = 0
        self.copy_from = None
        self.change_from = None

    def __repr__(self):
        return "<DumpEntry %r>" % dict.__repr__(self)


class Dump(object):
    """
    That class will read a dump file and store information about it.

    Besides iterating through the entries, this class is also capable
    of providing the complete tree (a dictionary like {path: entry, ...})
    for any given revision. This is important in cases where a given
    path is not being considered, but some entry is copied from it into
    a path which is being considered.

    The mechanism used to build and store information about the whole dump
    tries to perform reasonably, without consuming an unacceptable amount
    of memory. Basically, there's an on-disk tree cache which saves a
    complete tree state (trees are path -> dump entry mappings) each 100
    revisions, or whenever the tree contains copies of previous trees.
    Then, whenever a tree has to be rebuilt for a given revision, the
    largest cached tree revision before the asked revision is taken,
    and the tree is incremented up to the asked revision. This ensures
    that the tree will never be incremented for more than 99 revisions, and
    will never "walk back" (since all trees that need copies are already
    cached).
    """

    def __init__(self, file=None, log=None):
        self._dump = []           # [entry, ... ]
        self._revision_index = {} # {revno: dump index, ...}
        self._revision_slice = {} # {revno: dump slice, ...}
        self._revision_order = [] # [revno, ... ]

        self._tree_cache_filename = tempfile.mktemp('-saved-trees')
        self._tree_cache = anydbm.open(self._tree_cache_filename, "c")
        self._tree_cache_mem = {}
        self._tree_cache_mem_order = []

        self._path_id = {} # {path: id, ...}
        self._id_path = {} # {id: path, ...}

        self._log = log or get_logger()

        self._file = file
        self._read()

    def __del__(self):
        os.unlink(self._tree_cache_filename)

    def _save_tree(self, revno, tree):
        self._log.debug("Saving revision %d in disk cache" % revno)
        self._tree_cache[str(revno)] = bz2.compress(marshal.dumps(tree, 2))

    def _load_tree(self, revno):
        self._log.debug("Loading revision %d from disk cache" % revno)
        return marshal.loads(bz2.decompress(self._tree_cache[str(revno)]))

    def _build_tree(self, revno):
        if revno in self._tree_cache_mem:
            self._log.debug("Found revision %d in memory cache" % revno)
            return self._tree_cache_mem[revno]
        if str(revno) in self._tree_cache:
            return self._load_tree(revno)
        tree_revno = -1
        for cached_revno_s in self._tree_cache:
            cached_revno = int(cached_revno_s)
            if tree_revno < cached_revno < revno:
                tree_revno = cached_revno
        if tree_revno != -1:
            self._log.debug("Building revision %d based on %d" %
                            (revno, tree_revno))
            tree = self._load_tree(tree_revno)
        else:
            self._log.debug("Building revision %d from scratch" % revno)
            tree = {}
        for current_revno in self._revision_order:
            if tree_revno < current_revno:
                slice = self._revision_slice[current_revno]
                for entry_index in range(slice.start, slice.stop):
                    self._change_tree(tree, self._dump[entry_index],
                                      entry_index)
                if current_revno == revno:
                    break
        if len(self._tree_cache_mem) > 3:
            del self._tree_cache_mem[self._tree_cache_mem_order[0]]
            del self._tree_cache_mem_order[0]
        self._tree_cache_mem[revno] = tree
        self._tree_cache_mem_order.append(revno)
        return tree

    def __iter__(self):
        return iter(self._dump)

    def get_revision(self, revno):
        return self._dump[self._revision_index[revno]]

    def get_revision_entries(self, revno, path=None, incremental=True):
        if incremental and not path:
            return self._dump[self._revision_slice[revno]]
        else:
            raise NotImplementedError

    def get_entry(self, revno, path):
        tree = self._build_tree(revno)
        return self._dump[tree[self._path_id[path]]]

    def get_entry_content(self, entry):
        if entry.content_len == 0:
            return ""
        self._file.seek(entry.content_pos)
        return self._file.read(entry.content_len)

    def get_tree(self, revno):
        tree = self._build_tree(revno)
        path_tree = {}
        id_path = self._id_path
        for tree_path_id in tree.keys():
            path_tree[id_path[tree_path_id]] = self._dump[tree[tree_path_id]]
        return path_tree

    def get_dir_tree(self, revno, path):
        tree = self._build_tree(revno)
        path_tree = {}
        id_path = self._id_path
        prefix = path+"/"
        for tree_path_id in tree.keys():
            tree_path = id_path[tree_path_id]
            if tree_path == path or tree_path.startswith(prefix):
                path_tree[tree_path] = self._dump[tree[tree_path_id]]
        return path_tree

    def _change_tree(self, tree, entry, entry_index, building=False):

        node_action = entry["node-action"]
        node_path = entry["node-path"]

        path_id = self._path_id
        id_path = self._id_path

        if node_path not in path_id:
            new_id = len(path_id)
            path_id[node_path] = new_id
            id_path[new_id] = node_path

        node_path_id = path_id[node_path]

        copied_something = False

        if node_action == "add":
            assert node_path not in tree
            tree[node_path_id] = entry_index

            node_kind = entry["node-kind"]

            if "node-copyfrom-path" in entry:

                copied_something = True

                copy_path = entry["node-copyfrom-path"]
                copy_revno = int(entry["node-copyfrom-rev"])

                copy_tree = self._build_tree(copy_revno)

                entry.copy_from = self._dump[copy_tree[path_id[copy_path]]]

                if building:
                    if "prop-content-length" not in entry:
                        entry.prop = entry.copy_from.prop
                    elif "text-content-length" not in entry:
                        entry.content_pos = entry.copy_from.content_pos
                        entry.content_len = entry.copy_from.content_len

                if node_kind == "dir":
                    # Add entries inside the directory to the tree.
                    prefix = copy_path+"/"
                    def relocate(path):
                        return os.path.join(node_path,
                                            path[len(prefix):])
                    for tree_path_id, tree_entry_index in copy_tree.items():
                        tree_path = id_path[tree_path_id]
                        if tree_path.startswith(prefix):
                            # Would we need a new entry with copy_from?
                            relocated_path = relocate(tree_path)
                            if relocated_path not in path_id:
                                new_id = len(path_id)
                                path_id[relocated_path] = new_id
                                id_path[new_id] = relocated_path
                            tree[path_id[relocated_path]] = tree_entry_index


        elif node_action == "change":

            if node_path_id not in tree:
                raise IncrementalDumpError, \
                      "Dump references a missing revision"

            if building:
                entry.change_from = self._dump[tree[node_path_id]]

                if "prop-content-length" not in entry:
                    entry.prop = entry.change_from.prop
                elif "text-content-length" not in entry:
                    entry.content_pos = entry.change_from.content_pos
                    entry.content_len = entry.change_from.content_len

            tree[node_path_id] = entry_index

        elif node_action == "delete":

            if node_path_id not in tree:
                raise IncrementalDumpError, \
                      "Dump references a missing revision"

            tree_entry = self._dump[tree[node_path_id]]

            if tree_entry["node-kind"] == "dir":
                prefix = node_path+"/"
                for tree_path_id in tree.keys():
                    if id_path[tree_path_id].startswith(prefix):
                        del tree[tree_path_id]

            del tree[node_path_id]

        return copied_something

    def _read(self):

        file = self._file

        convert_to_int = {}
        for name in ["revision-number",
                     "content-length",
                     "prop-content-length",
                     "text-content-length",
                     "node-copyfrom-rev"]:
            convert_to_int[intern(name)] = True

        revision = revision_index = None
        last_saved_len = 0
        copied_something = False

        tree = {}

        revno = -1

        while True:

            line = file.readline()
            if not line:
                break
            line = line.rstrip()
            if not line:
                continue

            # Build entry

            entry = DumpEntry()

            while line:

                field, value = line.split(': ', 1)
                field = intern(field.lower())

                if field in convert_to_int:
                    entry[field] = int(value)
                else:
                    entry[field] = value

                line = file.readline().rstrip()

            prop_content_length = int(entry.get("prop-content-length", 0))
            if prop_content_length:

                line = file.readline().rstrip()

                while line != "PROPS-END":

                    k, l = line.split(' ')
                    assert k == "K"
                    key = intern(file.read(int(l)))

                    file.readline()
                    line = file.readline().rstrip()

                    v, l = line.split(' ')
                    assert v == "V"
                    v_len = int(l)
                    if key in convert_to_int:
                        entry.prop[key] = int(file.read(v_len))
                    else:
                        entry.prop[key] = file.read(v_len)

                    file.readline()
                    line = file.readline().rstrip()

            entry.content_len = entry.get("text-content-length", 0)
            if entry.content_len:
                entry.content_pos = file.tell()
                file.seek(entry.content_len, 1)

            # The entry was read. Now process it.

            current_index = len(self._dump)

            if "node-path" in entry:

                copied_something |= self._change_tree(tree, entry,
                                                      current_index,
                                                      building=True)

            elif "revision-number" in entry:

                if revision:
                    self._log.info("Revision %d read" % revno)
                    self._log.debug("Tree has %d entries" % len(tree))

                    self._revision_index[revno] = revision_index
                    self._revision_slice[revno] = slice(revision_index+1,
                                                        current_index)
                    self._revision_order.append(revno)

                    if (copied_something or
                        (last_saved_len+100 <= len(self._revision_index))):
                        last_saved_len = len(self._revision_index)
                        self._save_tree(revno, tree)
                    else:
                        if len(self._tree_cache_mem) > 3:
                            top = self._tree_cache_mem_order[0]
                            del self._tree_cache_mem[top]
                            del self._tree_cache_mem_order[0]
                        self._tree_cache_mem[revno] = tree.copy()
                        self._tree_cache_mem_order.append(revno)

                revno = entry["revision-number"]
                revision = entry
                revision_index = current_index

                copied_something = False

            elif "svn-fs-dump-format-version" in entry:

                format_version = entry["svn-fs-dump-format-version"]
                if format_version != "2":
                    raise FormatVersionError, \
                          "Invalid dump format version: %s" % format_version

            self._dump.append(entry)


def svn2bzr(dump_file, output_dir, creator_class=None, prefix=None, filter=[]):

    if os.path.exists(output_dir):
        raise Error, "%s already exists" % output_dir

    if creator_class is None:
        creator_class = SingleBranchCreator

    dump = Dump(dump_file)

    os.mkdir(output_dir)

    creator = creator_class(dump, output_dir, prefix)

    for include, regexp in filter:
        creator.add_filter(include, regexp)

    creator.run()


def append_filter(option, opt, value, parser):
    lst = getattr(parser.values, option.dest)
    if type(lst) is not list:
        lst = []
        setattr(parser.values, option.dest, lst)
    lst.append((opt == "--include", value))


def parse_options():
    parser = optparse.OptionParser("svn2bzr.py [options] "
                                   "<dump file> <output dir>",
                                   version="%prog "+VERSION)
    parser.defaults["filter"] = []
    parser.add_option("--include", dest="filter", metavar="REGEXP",
                      type="string", action="callback", callback=append_filter,
                      help="paths matching the regular expression are "
                           "considered if no prior exclude matched")
    parser.add_option("--exclude", dest="filter", metavar="REGEXP",
                      type="string", action="callback", callback=append_filter,
                      help="paths matching the regular expression are "
                           "discarded if no prior include matched")
    parser.add_option("--prefix", metavar="PATH", type="string",
                      help="Subversion repository will be considered as if "
                           "it started at the given path")
    parser.add_option("--scheme", metavar="SCHEME", type="string",
                      help="Subversion repository scheme (single or trunk, "
                           "default is single)",
                      default="single")
    parser.add_option("--log", metavar="LEVEL",
                      help="set logging level to LEVEL (debug, info, "
                           "warning, error)", default="info")
    opts, args = parser.parse_args()
    if len(args) != 2:
        parser.print_help()
        sys.exit(1)
    opts.args = args
    return opts


def main():

    opts = parse_options()

    if opts.scheme == "trunk":
        creator_class = TrunkBranchCreator
    else:
        creator_class = SingleBranchCreator

    log = get_logger()
    log.setLevel(logging.getLevelName(opts.log.upper()))

    dump_filename = opts.args[0]
    if dump_filename.endswith(".gz"):
        import gzip
        dump_file = gzip.GzipFile(dump_filename)
    elif dump_filename.endswith(".bz2"):
        dump_file = bz2.BZ2File(dump_filename)
    else:
        dump_file = open(dump_filename)

    try:
        svn2bzr(dump_file, opts.args[1], creator_class,
                opts.prefix, opts.filter)
    except Error, e:
        sys.exit("error: %s" % e)
    except KeyboardInterrupt:
        sys.exit("Interrupted")

if __name__ == "__main__":
    main()

