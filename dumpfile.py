#!/usr/bin/env python2.4
#
# Copyright (C) 2005 by Canonical Ltd
#
# Written by Gustavo Niemeyer <gustavo@niemeyer.net>
# Bugfixes and additional features by Jelmer Vernooij <jelmer@samba.org>
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
import anydbm
import time
import bz2

class FormatVersionError(StandardError): pass
class IncrementalDumpError(StandardError): pass

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
    complete tree state (trees are path -> dump entry mappings) each 
    DEFAULT_CACHE_INTERVAL revisions, or whenever the tree contains copies of 
    previous trees. Then, whenever a tree has to be rebuilt for a given 
    revision, the largest cached tree revision before the asked revision is 
    taken, and the tree is incremented up to the asked revision. This ensures
    that the tree will never be incremented for more than 99 revisions, and
    will never "walk back" (since all trees that need copies are already
    cached).
    """

    DEFAULT_CACHE_INTERVAL = 100

    def __init__(self, file=None, log=None, cache_interval=DEFAULT_CACHE_INTERVAL):
        root = DumpEntry()
        root['node-action'] = 'add'
        root['node-kind'] = 'dir'
        root['node-path'] = ''
        
        self._dump = [root]       # [entry, ... ]
        self._revision_index = {} # {revno: dump index, ...}
        self._revision_slice = {} # {revno: dump slice, ...}
        self._revision_order = [] # [revno, ... ]

        self._tree_cache_interval = cache_interval
        self._tree_cache_filename = tempfile.mktemp('-saved-trees')
        self._tree_cache = anydbm.open(self._tree_cache_filename, "c")
        self._tree_cache_mem = {}
        self._tree_cache_mem_order = []

        self._path_id = {'': 0} # {path: id, ...}
        self._id_path = {0: ''} # {id: path, ...}

        self._log = log

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
        for cached_revno in self._tree_cache_mem:
            if tree_revno <= cached_revno < revno:
                tree_revno = cached_revno
        if tree_revno != -1:
            self._log.debug("Building revision %d based on %d" %
                            (revno, tree_revno))
            if tree_revno in self._tree_cache_mem:
                tree = self._tree_cache_mem[tree_revno]
            else:
                tree = self._load_tree(tree_revno)
        else:
            self._log.debug("Building revision %d from scratch" % revno)
            tree = {}
        for current_revno in self._revision_order:
            if current_revno > revno:
                break
            elif tree_revno < current_revno:
                slice = self._revision_slice[current_revno]
                for entry_index in range(slice.start, slice.stop):
                    self._change_tree(tree, self._dump[entry_index],
                                      entry_index)
                if current_revno == revno:
                    break
        self._log.debug("Revision %d is ready" % revno)
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
                      "Dump references missing node %s with id %d" % (node_path, node_path_id)

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
                      "Dump references missing node %s with id %d" % (node_path, node_path_id)

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

        revision = {}
        revision_index = 0
        last_saved_len = 0
        copied_something = False

        tree = {0:0}

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

                field, value = line.split(':', 1)
                if value != "":
                    value = value[1:]
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

                self._log.info("Revision %d read" % entry['revision-number'])
                self._log.debug("Tree has %d entries" % len(tree))

                self._revision_index[revno] = revision_index
                self._revision_slice[revno] = slice(revision_index+1,
                                                    current_index)
                self._revision_order.append(revno)

                if (copied_something or
                    (last_saved_len + self._tree_cache_interval <= len(self._revision_index))):
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

