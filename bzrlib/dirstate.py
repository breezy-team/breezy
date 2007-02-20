# Copyright (C) 2006, 2007 Canonical Ltd
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

"""DirState objects record the state of a directory and its bzr metadata.

Pseudo EBNF grammar for the state file. Fields are separated by NULLs, and
lines by NL. The field delimiters are ommitted in the grammar, line delimiters
are not - this is done for clarity of reading. All string data is in utf8.

MINIKIND = "f" | "d" | "l" | "a" | "r";
NL = "\n";
NULL = "\0";
WHOLE_NUMBER = {digit}, digit;
BOOLEAN = "y" | "n";
REVISION_ID = a non-empty utf8 string;

dirstate format = header line, full checksum, row count, parent details,
 ghost_details, entries;
header line = "#bazaar dirstate flat format 2", NL;
full checksum = "adler32: ", ["-"], WHOLE_NUMBER, NL;
row count = "num_entries: ", digit, NL;
parent_details = WHOLE NUMBER, {REVISION_ID}* NL;
ghost_details = WHOLE NUMBER, {REVISION_ID}*, NL;
entries = {entry};
entry = entry_key, current_entry_details, {parent_entry_details};
entry_key = dirname,  basename, fileid;
current_entry_details = common_entry_details, working_entry_details;
parent_entry_details = common_entry_details, history_entry_details;
common_entry_details = MINIKIND, fingerprint, size, executable
working_entry_details = packed_stat
history_entry_details = REVISION_ID;
executable = BOOLEAN;
size = WHOLE_NUMBER;
fingerprint = a nonempty utf8 sequence with meaning defined by minikind.

Given this definition, the following is useful to know:
entry (aka row) - all the data for a given key.
entry[0]: The key (dirname, basename, fileid)
entry[0][0]: dirname
entry[0][1]: basename
entry[0][2]: fileid
entry[1]: The tree(s) data for this path and id combination.
entry[1][0]: The current tree
entry[1][1]: The second tree

For an entry for a tree, we have (using tree 0 - current tree) to demonstrate:
entry[1][0][0]: kind
entry[1][0][1]: fingerprint
entry[1][0][2]: size
entry[1][0][3]: executable
entry[1][0][4]: packed_stat
OR (for non tree-0)
entry[1][1][4]: revision_id

There may be multiple rows at the root, one per id present in the root, so the in memory root row is now:
_root_entries[0][0]: ''
_root_entries[0][1]: ''
_root_entries[0][2]: file_id
_root_entries[1][0]: The tree data for the current tree for this fileid at /
etc.

Kinds:
'r' is a relocated entry: This path is not present in this tree with this id,
    but the id can be found at another location. The fingerprint is used to
    point to the target location.
'a' is an absent entry: In that tree the id is not present at this path.
'd' is a directory entry: This path in this tree is a directory with the
    current file id. There is no fingerprint for directories.
'f' is a file entry: As for directory, but its a file. The fingerprint is a
    sha1 value.
'l' is a symlink entry: As for directory, but a symlink. The fingerprint is the
    link target.


--- Format 1 had the following different definition: ---
rows = dirname, NULL, basename, NULL, MINIKIND, NULL, fileid_utf8, NULL,
    WHOLE NUMBER (* size *), NULL, packed stat, NULL, sha1|symlink target, 
    {PARENT ROW}
PARENT ROW = NULL, revision_utf8, NULL, MINIKIND, NULL, dirname, NULL,
    basename, NULL, WHOLE NUMBER (* size *), NULL, "y" | "n", NULL,
    SHA1

PARENT ROW's are emitted for every parent that is not in the ghosts details
line. That is, if the parents are foo, bar, baz, and the ghosts are bar, then
each row will have a PARENT ROW for foo and baz, but not for bar.


In any tree, a kind of 'moved' indicates that the fingerprint field
(which we treat as opaque data specific to the 'kind' anyway) has the
details for the id of this row in that tree.

I'm strongly tempted to add a id->path index as well, but I think that
where we need id->path mapping; we also usually read the whole file, so
I'm going to skip that for the moment, as we have the ability to locate
via bisect any path in any tree, and if we lookup things by path, we can
accumulate a id->path mapping as we go, which will tend to match what we
looked for.

I plan to implement this asap, so please speak up now to alter/tweak the
design - and once we stabilise on this, I'll update the wiki page for
it.

The rationale for all this is that we want fast operations for the
common case (diff/status/commit/merge on all files) and extremely fast
operations for the less common but still occurs a lot status/diff/commit
on specific files). Operations on specific files involve a scan for all
the children of a path, *in every involved tree*, which the current
format did not accommodate. 
----

Design priorities:
 1) Fast end to end use for bzr's top 5 uses cases. (commmit/diff/status/merge/???)
 2) fall back current object model as needed.
 3) scale usably to the largest trees known today - say 50K entries. (mozilla
    is an example of this)


Locking:
 Eventually reuse dirstate objects across locks IFF the dirstate file has not
 been modified, but will require that we flush/ignore cached stat-hit data
 because we wont want to restat all files on disk just because a lock was
 acquired, yet we cannot trust the data after the previous lock was released.

Memory representation:
 vector of all directories, and vector of the childen ?
   i.e. 
     root_entrie = (direntry for root, [parent_direntries_for_root]), 
     dirblocks = [
     ('', ['data for achild', 'data for bchild', 'data for cchild'])
     ('dir', ['achild', 'cchild', 'echild'])
     ]
    - single bisect to find N subtrees from a path spec
    - in-order for serialisation - this is 'dirblock' grouping.
    - insertion of a file '/a' affects only the '/' child-vector, that is, to
      insert 10K elements from scratch does not generates O(N^2) memoves of a
      single vector, rather each individual, which tends to be limited to a 
      manageable number. Will scale badly on trees with 10K entries in a 
      single directory. compare with Inventory.InventoryDirectory which has
      a dictionary for the children. No bisect capability, can only probe for
      exact matches, or grab all elements and sorta.
    - Whats the risk of error here? Once we have the base format being processed
      we should have a net win regardless of optimality. So we are going to 
      go with what seems reasonably.
open questions:

maybe we should do a test profile of these core structure - 10K simulated searches/lookups/etc?

Objects for each row?
The lifetime of Dirstate objects is current per lock, but see above for
possible extensions. The lifetime of a row from a dirstate is expected to be
very short in the optimistic case: which we are optimising for. For instance,
subtree status will determine from analysis of the disk data what rows need to
be examined at all, and will be able to determine from a single row whether
that file has altered or not, so we are aiming to process tens of thousands of
entries each second within the dirstate context, before exposing anything to
the larger codebase. This suggests we want the time for a single file
comparison to be < 0.1 milliseconds. That would give us 10000 paths per second
processed, and to scale to 100 thousand we'll another order of magnitude to do
that. Now, as the lifetime for all unchanged entries is the time to parse, stat
the file on disk, and then immediately discard, the overhead of object creation
becomes a significant cost.

Figures: Creating a tuple from from 3 elements was profiled at 0.0625
microseconds, whereas creating a object which is subclassed from tuple was
0.500 microseconds, and creating an object with 3 elements and slots was 3
microseconds long. 0.1 milliseconds is 100 microseconds, and ideally we'll get
down to 10 microseconds for the total processing - having 33% of that be object
creation is a huge overhead. There is a potential cost in using tuples within
each row which is that the conditional code to do comparisons may be slower
than method invocation, but method invocation is known to be slow due to stack
frame creation, so avoiding methods in these tight inner loops in unfortunately
desirable. We can consider a pyrex version of this with objects in future if
desired.

"""


import base64
import bisect
import cStringIO
import os
import sha
import struct
import zlib

from bzrlib import (
    errors,
    trace,
    )
import bzrlib.inventory
from bzrlib import osutils
from bzrlib.osutils import (
    pathjoin,
    sha_file,
    sha_string,
    walkdirs,
    )


class DirState(object):
    """Record directory and metadata state for fast access.

    A dirstate is a specialised data structure for managing local working
    tree state information. Its not yet well defined whether it is platform
    specific, and if it is how we detect/parameterise that.
    """

    _kind_to_minikind = {'absent':'a', 'file':'f', 'directory':'d', 'relocated':'r', 'symlink':'l'}
    _minikind_to_kind = {'a':'absent', 'f':'file', 'd':'directory', 'l':'symlink', 'r':'relocated'}
    _to_yesno = {True:'y', False: 'n'} # TODO profile the performance gain
     # of using int conversion rather than a dict here. AND BLAME ANDREW IF
     # it is faster.

    NOT_IN_MEMORY = 0
    IN_MEMORY_UNMODIFIED = 1
    IN_MEMORY_MODIFIED = 2

    # A pack_stat (the x's) that is just noise and will never match the output
    # of base64 encode.
    NULLSTAT = 'x' * 32
    NULL_PARENT_DETAILS = ('absent', '', 0, False, '')

    def __init__(self):
        """Create a  DirState object.

        Attributes of note:

        :attr _root_entrie: The root row of the directory/file information,
            - contains the path to / - '', ''
            - kind of 'directory',
            - the file id of the root in utf8
            - size of 0
            - a packed state
            - and no sha information.
        """
        # _header_state and _dirblock_state represent the current state
        # of the dirstate metadata and the per-row data respectiely.
        # NOT_IN_MEMORY indicates that no data is in memory
        # IN_MEMORY_UNMODIFIED indicates that what we have in memory
        #   is the same as is on disk
        # IN_MEMORY_MODIFIED indicates that we have a modified version
        #   of what is on disk. 
        # In future we will add more granularity, for instance _dirblock_state
        # will probably support partially-in-memory as a separate variable,
        # allowing for partially-in-memory unmodified and partially-in-memory
        # modified states.
        self._header_state = DirState.NOT_IN_MEMORY
        self._dirblock_state = DirState.NOT_IN_MEMORY
        self._dirblocks = []
        self._ghosts = []
        self._parents = []
        self._root_entries = None
        self._state_file=None

    def add(self, path, file_id, kind, stat, link_or_sha1):
        """Add a path to be tracked.

        :param path: The path within the dirstate - '' is the root, 'foo' is the
            path foo within the root, 'foo/bar' is the path bar within foo 
            within the root.
        :param file_id: The file id of the path being added.
        :param kind: The kind of the path.
        :param stat: The output of os.lstate for the path.
        :param link_or_sha1: The sha value of the file, or the target of a
            symlink. '' for directories.
        """
        # adding a file:
        # find the block its in. 
        # find the location in the block.
        # check its not there
        # add it.
        #------- copied from bzrlib.inventory.make_entry
        # --- normalized_filename wants a unicode basename only, so get one.
        dirname, basename = os.path.split(path)
        # we dont import normalized_filename directly because we want to be
        # able to change the implementation at runtime for tests.
        norm_name, can_access = osutils.normalized_filename(basename)
        if norm_name != basename:
            if can_access:
                basename = norm_name
            else:
                raise errors.InvalidNormalization(path)
        # now that we've normalised, we need the correct utf8 path and 
        # dirname and basename elements. This single encode and split should be
        # faster than three separate encodes.
        utf8path = (dirname + '/' + basename).strip('/').encode('utf8')
        dirname, basename = os.path.split(utf8path)
        self._read_dirblocks_if_needed()
        block_index = self._find_dirblock_index(dirname)
        if block_index < 0:
            # some parent path has not been added - its an error to add this
            # child
            raise errors.NotVersionedError(path, str(self))
        block = self._dirblocks[block_index][1]
        if stat is None:
            size = 0
            packed_stat = DirState.NULLSTAT
        else:
            size = stat.st_size
            packed_stat = pack_stat(stat)
        parent_info = self._empty_parent_info()
        entry_key = (dirname, basename, file_id.encode('utf8'))
        if kind == 'file':
            entry_data = entry_key, [
                (kind, link_or_sha1, size, False, packed_stat),
                ] + parent_info
        elif kind == 'directory':
            entry_data = entry_key, [
                (kind, '', 0, False, packed_stat),
                ] + parent_info
        elif kind == 'symlink':
            entry_data = entry_key, [
                (kind, link_or_sha1, size, False, packed_stat),
                ] + parent_info
        else:
            raise errors.BzrError('unknown kind %r' % kind)
        entry_index = bisect.bisect_left(block, entry_data)
        if len(block) > entry_index:
            assert block[entry_index][0][1] != basename, \
                "basename %r already added" % basename
        block.insert(entry_index, entry_data)

        if kind == 'directory':
           # insert a new dirblock
           self._ensure_block(block_index, entry_index, utf8path)
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED

    def add_deleted(self, fileid_utf8, parents):
        """Add fileid_utf8 with parents as deleted."""
        self._read_dirblocks_if_needed()
        new_row = self._make_deleted_row(fileid_utf8, parents)
        block_index = self._find_dirblock_index(new_row[0][0])
        if block_index < 0:
            # no deleted block yet.
            bisect.insort_left(self._dirblocks, (new_row[0][0], []))
            block_index = self._find_dirblock_index(new_row[0][0])
        block = self._dirblocks[block_index][1]
        row_index = bisect.insort_left(block, new_row)
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED

    def _empty_parent_info(self):
        return [DirState.NULL_PARENT_DETAILS] * (len(self._parents) -
                                                    len(self._ghosts))

    def _ensure_block(self, parent_block_index, parent_row_index, dirname):
        """Enssure a block for dirname exists.
        
        This function exists to let callers which know that there is a
        directory dirname ensure that the block for it exists. This block can
        fail to exist because of demand loading, or because a directory had no
        children. In either case it is not an error. It is however an error to
        call this if there is no parent entry for the directory, and thus the
        function requires the coordinates of such an entry to be provided.

        The root row is special cased and can be indicated with a parent block
        and row index of -1

        :param parent_block_index: The index of the block in which dirname's row
            exists.
        :param parent_row_index: The index in the parent block where the row
            exists.
        :param dirname: The utf8 dirname to ensure there is a block for.
        :return: The index for the block.
        """
        # the basename of the directory must be the end of its full name.
        if not (parent_block_index == -1 and
            parent_block_index == -1 and dirname == ''):
            assert dirname.endswith(
                self._dirblocks[parent_block_index][1][parent_row_index][0][1])
        ## In future, when doing partial parsing, this should load and 
        # populate the entire block.
        index = bisect.bisect_left(self._dirblocks, (dirname, []))
        if (index == len(self._dirblocks) or
            self._dirblocks[index][0] != dirname):
            self._dirblocks.insert(index, (dirname, []))
        return index

    def _entries_to_current_state(self, new_entries):
        """Load new_entries into self._root_entries and self.dirblocks.

        Process new_entries into the current state object, making them the active
        state.

        :param new_entries: A sorted list of entries. This function does not sort
            to prevent unneeded overhead when callers have a sorted list already.
        :return: Nothing.
        """
        assert new_entries[0][0][0:2] == ('', ''), \
            "Missing root row %r" % new_entries[0][0]
        self._root_entries = []
        self._dirblocks = [('', [])]
        current_block = self._root_entries
        current_dirname = ''
        root_key = ('', '')
        for entry in new_entries:
            if entry[0][0] != current_dirname:
                # new block
                current_block = []
                self._dirblocks.append((entry[0][0], current_block))
            elif entry[0][0:2] != root_key:
                # this is not a root entry for a tree
                current_block = self._dirblocks[-1][1]
            # append the entry to the current block
            current_block.append(entry)
    
    def _entry_to_line(self, entry):
        """Serialize entry to a NULL delimited line ready for _get_output_lines.
        
        :param entry: An entry_tuple as defined in the module docstring.
        """
        entire_entry = list(entry[0])
        for tree_number, tree_data in enumerate(entry[1]):
            # (kind, fingerprint, size, executable, tree_specific_string)
            entire_entry.extend(tree_data)
            # 3 for the key, 5 for the fields per tree.
            tree_offset = 3 + tree_number * 5
            # kind
            entire_entry[tree_offset + 0] = DirState._kind_to_minikind[tree_data[0]]
            # size
            entire_entry[tree_offset + 2] = str(tree_data[2])
            # executable
            entire_entry[tree_offset + 3] = DirState._to_yesno[tree_data[3]]
        return '\0'.join(entire_entry)

    def _find_block(self, key, add_if_missing=False):
        """Return the block that key should be present in.

        :param key: A dirstate entry key.
        :return: The block tuple.
        """
        if key[0:2] == ('', ''):
            return self._root_entries
        else:
            block_index, present = self._find_block_index_from_key(key)
            if not present:
                if add_if_missing:
                    self._dirblocks.insert(block_index, (key[0], []))
                else:
                    # some parent path has not been added - its an error to add this
                    # child
                    raise errors.NotVersionedError(key[0:2], str(self))
            return self._dirblocks[block_index]

    def _find_block_index_from_key(self, key):
        """Find the dirblock index for a key.

        :return: The block index, True if the block for the key is present.
        """
        block_index = bisect.bisect_left(self._dirblocks, (dirname, []))
        present = (block_index < len(self._dirblocks) and
            self._dirblocks[block_index][0] == dirname)
        return block_index, present

    def _find_dirblock_index(self, dirname):
        """Find the dirblock index for dirname.

        :return: -1 if the dirname is not present, or the index in
            self._dirblocks for it otherwise.
        """
        block_index = bisect.bisect_left(self._dirblocks, (dirname, []))
        if (block_index == len(self._dirblocks) or
            self._dirblocks[block_index][0] != dirname):
            return -1
        return block_index

    def _find_entry_index(self, key, block):
        """Find the entry index for a key in a block.

        :return: The entry index, True if the entry for the key is present.
        """
        entry_index = bisect.bisect_left(block, (key, []))
        present = (entry_index < len(block) and
            block[entry_index][0] == key)
        return entry_index, present

    @staticmethod
    def from_tree(tree, dir_state_filename):
        """Create a dirstate from a bzr Tree.

        :param tree: The tree which should provide parent information and
            inventory ids.
        """
        tree.lock_read()
        # XXX: aka the big ugly.: To fix this, turn it into:
        # init; set_path_id(root); set_parents(tree.get_parnets); write_inventory(tree.inventory)
        result = DirState()
        result._state_file = open(dir_state_filename, 'wb+')

        _encode = base64.encodestring

        parent_ids = tree.get_parent_ids()
        num_parents = len(parent_ids)
        if num_parents > 3:
            raise ValueError('Cannot handle more than 3 parents')

        parent_trees = []
        for parent_id in parent_ids:
            parent_trees.append(tree.branch.repository.revision_tree(parent_id))
            parent_trees[-1].lock_read()
        all_trees = [tree] + parent_trees
        num_trees = len(all_trees)

        # FIXME: is this utf8 safe?

        to_minikind = DirState._kind_to_minikind
        to_yesno = DirState._to_yesno

        st = os.lstat(tree.basedir)
        root_entries = []
        dirblocks = []
        for tree_index, tree in enumerate(all_trees):
            for path, tree_entry in tree.iter_entries_by_dir():
                dirname, basename = os.path.split(path.encode('utf8'))
                file_id = tree_entry.file_id.encode('utf8')
                kind = tree_entry.kind
                if kind == 'directory':
                    fingerprint = ''
                    size = 0
                    executable = False
                elif kind == 'symlink':
                    fingerprint = tree.symlink_target(path)
                    size = 0
                    executable = False
                elif kind == 'file':
                    fingerprint = tree.get_file_sha1(tree_entry.file_id, path)
                    size = tree_entry.text_size
                    executable = tree.is_executable(tree_entry.file_id, path)
                else:
                    raise Exception

                key = (dirname, basename, file_id)
                if (dirname, basename) == ('', ''):
                    block = root_entries
                else:
                    # not a root entry
                    block_index = bisect.bisect_left(dirblocks, (dirname, []))
                    if block_index == len(dirblocks) or dirblocks[block_index][0] != dirname:
                        # no dirblock yet.
                        dirblocks.insert(block_index, (dirname, []))
                    block = dirblocks[block_index][1]
                # find the data for this path within block:
                entry_index = bisect.bisect_left(block, (key,))
                if entry_index == len(block) or block[entry_index][0] != key:
                    # new key in this block, add blank data
                    block.insert(entry_index, (key, [None] * num_trees))
                # get the right form of data for this trees type
                if tree_index == 0:
                    # current tree
                    st = os.lstat(tree.abspath(path))
                    tree_data = pack_stat(st)
                    if kind == 'file':
                        size = st.st_size
                else:
                    tree_data = tree_entry.revision.encode('utf8')
                block[entry_index][1][tree_index] = (
                    kind,
                    fingerprint,
                    size,
                    executable,
                    tree_data)

        result._set_data(parent_ids, root_entries, dirblocks)
        result.save()
        for tree in all_trees:
            tree.unlock()
        return result

    def get_ghosts(self):
        """Return a list of the parent tree revision ids that are ghosts."""
        self._read_header_if_needed()
        return self._ghosts

    def get_lines(self):
        """Serialise the entire dirstate to a sequence of lines."""
        if (self._header_state == DirState.IN_MEMORY_UNMODIFIED and
            self._dirblock_state == DirState.IN_MEMORY_UNMODIFIED):
            # read whats on disk.
            self._state_file.seek(0)
            return self._state_file.readlines()
        lines = []
        lines.append(self._get_parents_line(self.get_parent_ids()))
        lines.append(self._get_ghosts_line(self._ghosts))
        # append the root line which is special cased
        lines.extend(map(self._entry_to_line, self._iter_entries()))
        return self._get_output_lines(lines)

    def _get_ghosts_line(self, ghost_ids):
        """Create a line for the state file for ghost information."""
        return '\0'.join([str(len(ghost_ids))] + ghost_ids)

    def _get_parents_line(self, parent_ids):
        """Create a line for the state file for parents information."""
        return '\0'.join([str(len(parent_ids))] + parent_ids)

    def get_parent_ids(self):
        """Return a list of the parent tree ids for the directory state."""
        self._read_header_if_needed()
        return list(self._parents)

    def _get_block_entry_index(self, dirname, basename, tree_index):
        """Get the coordinates for a path in the state structure.

        :param dirname: The utf8 dirname to lookup.
        :param basename: The utf8 basename to lookup.
        :param tree_index: The index of the tree for which this lookup should
            be attempted.
        :return: A tuple describing where the path is located, or should be
            inserted. The tuple contains four fields: the block index, the row
            index, anda two booleans are True when the directory is present, and
            when the entire path is present.  There is no guarantee that either
            coordinate is currently reachable unless the found field for it is
            True. For instance, a directory not present in the searched tree
            may be returned with a value one greater than the current highest
            block offset. The directory present field will always be True when
            the path present field is True. The directory present field does
            NOT indicate that the directory is present in the searched tree,
            rather it indicates that there are at least some files in some
            tree present there.
        """
        # looking up the root is not supported, because the root entries exist
        # outside the used coordinate system
        assert not (dirname == '' and basename == ''), 'blackhole lookup error'
        self._read_dirblocks_if_needed()
        block_index = bisect.bisect_left(self._dirblocks, (dirname, []))
        if (block_index == len(self._dirblocks) or
            self._dirblocks[block_index][0] != dirname):
            # no such directory - return the dir index and 0 for the row.
            return block_index, 0, False, False
        block = self._dirblocks[block_index][1] # access the entries only
        search = ((dirname, basename),)
        row_index = bisect.bisect_left(block, search)
        # linear search through present entries at this path to find the one
        # requested.
        while row_index < len(block) and block[row_index][0][1] == basename:
            if block[row_index][1][tree_index] not in ('absent', 'relocated'):
                return block_index, row_index, True, True
            row += 1
        return block_index, row_index, True, False

    def _get_entry(self, tree_index, fileid_utf8=None, path_utf8=None):
        """Get the dirstate entry for path in tree tree_index

        If either file_id or path is supplied, it is used as the key to lookup.
        If both are supplied, the fastest lookup is used, and an error is
        raised if they do not both point at the same row.
        
        :param tree_index: The index of the tree we wish to locate this path
            in. If the path is present in that tree, the entry containing its
            details is returned, otherwise (None, None) is returned
        :param fileid_utf8: A utf8 file_id to look up.
        :param path_utf8: An utf8 path to be looked up.
        :return: The dirstate entry tuple for path, or (None, None)
        """
        if path_utf8 is not None:
            assert path_utf8.__class__ == str, 'path_utf8 is not a str: %s %s' % (type(path_utf8), path_utf8)
        self._read_dirblocks_if_needed()
        if path_utf8 is not None:
            # path lookups are faster
            if path_utf8 == '':
                for entry in self._root_entries:
                    if entry[1][tree_index] not in ('absent', 'relocated'):
                        return entry
                raise Exception, 'rootless trees not supported yet'
            dirname, basename = os.path.split(path_utf8)
            block_index, entry_index, dir_present, file_present = \
                self._get_block_entry_index(dirname, basename, tree_index)
            if not file_present:
                return None, None
            entry = self._dirblocks[block_index][1][entry_index]
            assert entry[0][2] and entry[1][tree_index][0] not in ('absent', 'relocated'), 'unversioned entry?!?!'
            if fileid_utf8:
                if entry[0][2] != fileid_utf8:
                    raise BzrError('integrity error ? : mismatching tree_index, file_id and path')
            return entry
        else:
            for entry in self._iter_entries():
                if entry[0][2] == fileid_utf8:
                    if entry[1][tree_index][0] == 'relocated':
                        # look up the real location directly by path
                        return self._get_entry(tree_index,
                            fileid_utf8=fileid_utf8,
                            path_utf8=entry[1][tree_index][0])
                    if entry[1][tree_index][0] == 'absent':
                        # not in the tree at all.
                        return None, None
                    return entry
            return None, None

    @staticmethod
    def initialize(path):
        """Create a new dirstate on path.

        The new dirstate will be an empty tree - that is it has no parents,
        and only a root node - which has id ROOT_ID.

        :param path: The name of the file for the dirstate.
        :return: A DirState object.
        """
        # This constructs a new DirState object on a path, sets the _state_file
        # to a new empty file for that path. It then calls _set_data() with our
        # stock empty dirstate information - a root with ROOT_ID, no children,
        # and no parents. Finally it calls save() to ensure that this data will
        # persist.
        result = DirState()
        result._state_file = open(path, 'wb+')
        # a new root directory, with a NULLSTAT.
        root_entries = [(('', '', bzrlib.inventory.ROOT_ID), [
                ('directory', '', 0, False, DirState.NULLSTAT),
            ])]
        root_parents = []
        empty_tree_dirblocks = [('', [])] # root dir contents - no entries.
        result._set_data([], root_entries, empty_tree_dirblocks)
        try:
            result.save()
        except:
            result._state_file.close()
            raise
        return result

    def _inv_entry_to_details(self, inv_entry):
        """Convert an inventory entry (from a revision tree) to state details.

        :param inv_entry: An inventory entry whose sha1 and link targets can be
            relied upon, and which has a revision set.
        :return: A details tuple - the details for a single tree at a path +
            id.
        """
        kind = inv_entry.kind
        tree_data = inv_entry.revision.encode('utf8')
        assert len(tree_data) > 0, 'empty revision for the inv_entry.'
        if kind == 'directory':
            fingerprint = ''
            size = 0
            executable = False
        elif kind == 'symlink':
            fingerprint = inv_entry.symlink_target or ''
            size = 0
            executable = False
        elif kind == 'file':
            fingerprint = inv_entry.text_sha1 or ''
            size = inv_entry.text_size or 0
            executable = inv_entry.executable
        else:
            raise Exception
        return (kind, fingerprint, size, executable, tree_data)

    def _iter_entries(self, root_entries=None, dirblocks=None):
        """Iterate over all the entries in the dirstate.

        Each yelt item is an entry in the standard format described in the
        docstring of bzrlib.dirstate.

        :param root_entries: Allows overriding of the root entries to be
            reported.
        :param dirblocks: Allows overriding of the source dirblock data.
        """
        self._read_dirblocks_if_needed()
        if root_entries is None:
            root_entries = self._root_entries
        if dirblocks is None:
            dirblocks = self._dirblocks
        for entry in root_entries:
            yield entry
        for directory in dirblocks:
            for entry in directory[1]:
                yield entry

    def _get_output_lines(self, lines):
        """format lines for final output.

        :param lines: A sequece of lines containing the parents list and the
            path lines.
        """
        output_lines = ['#bazaar dirstate flat format 2\n']
        lines.append('') # a final newline
        inventory_text = '\0\n\0'.join(lines)
        output_lines.append('adler32: %s\n' % (zlib.adler32(inventory_text),))
        # -3, 1 for num parents, 1 for ghosts, 1 for final newline
        num_entries = len(lines)-3
        output_lines.append('num_entries: %s\n' % (num_entries,))
        output_lines.append(inventory_text)
        return output_lines

    def _make_deleted_row(self, fileid_utf8, parents):
        """Return a deleted for for fileid_utf8."""
        return ('/', 'RECYCLED.BIN', 'file', fileid_utf8, 0, DirState.NULLSTAT,
            ''), parents

    @staticmethod
    def on_file(path):
        """Construct a DirState on the file at path path."""
        result = DirState()
        result._state_file = open(path, 'rb+')
        return result

    def _read_dirblocks_if_needed(self):
        """Read in all the dirblocks from the file if they are not in memory.
        
        This populates self._root_entries and self._dirblocks, and sets 
        self._dirblock_state to IN_MEMORY_UNMODIFIED. It is not currently ready
        for incremental block loading.
        """
        self._read_header_if_needed()
        if self._dirblock_state == DirState.NOT_IN_MEMORY:
            # the _state_file pointer will be positioned at the start of the 
            # dirblocks.
            text = self._state_file.read()
            # TODO: check the adler checksums. adler_measured = zlib.adler32(text)

            fields = text.split('\0')
            # Remove the last blank entry
            trailing = fields.pop()
            assert trailing == ''
            # consider turning fields into a tuple.

            # skip the first field which is the trailing null from the header.
            cur = 1
            # Each line now has an extra '\n' field which is not used
            # so we just skip over it
            # entry size:
            #  3 fields for the key
            #  + number of fields per tree_data (5) * tree count
            #  + newline
            num_present_parents = len(self._parents) - len(self._ghosts)
            tree_count = 1 + num_present_parents
            entry_size = 3 + 5 * tree_count + 1
            expected_field_count = entry_size * self._num_entries
            if len(fields) - cur > expected_field_count:
                fields = fields[:expected_field_count + cur]
                trace.mutter('Unexpectedly long dirstate field count!')
                print "XXX: incorrectly truncated dirstate file bug triggered."
            field_count = len(fields)
            # this checks our adjustment, and also catches file too short.
            assert field_count - cur == expected_field_count, \
                'field count incorrect %s != %s, entry_size=%s, '\
                'num_entries=%s fields=%r' % (
                    field_count - cur, expected_field_count, entry_size,
                    self._num_entries, fields)

            # Fast path the case where there are 1 or 2 parents
            if num_present_parents == 0:
                # key, [current tree]
                entries = [(tuple(fields[pos:pos + 3]), [fields[pos + 3:pos + 8]])
                    for pos in xrange(cur, field_count, entry_size)]
            elif num_present_parents == 1:
                # key,
                entries = [(tuple(fields[pos:pos + 3]),
                #   [current tree,             parent 1]
                    [fields[pos + 3:pos + 8], fields[pos + 8:pos + 13], ])
                    for pos in xrange(cur, field_count, entry_size)]
            elif num_present_parents == 2:
                # key,
                entries = [(tuple(fields[pos:pos + 3]),
                #   [current tree,             parent 1, 
                    [fields[pos + 3:pos + 8], fields[pos + 8:pos + 13],
                #   parent 2]
                    fields[pos + 13:pos + 18], ])
                    for pos in xrange(cur, field_count, entry_size)]
            else:
                entries = [(
                    tuple(fields[pos:pos+3]), #key
                    tuple([fields[chunk:chunk+5] for 
                        chunk in xrange(pos + 3, pos+entry_size-1, 5)]))
                            for pos in xrange(cur, field_count, entry_size)
                ]

            assert len(entries) == self._num_entries, '%s != %s entries' % (len(entries),
                self._num_entries)

            def _line_to_entry(line):
                """Convert freshly read tree details to the final form.
                
                This converts size and minikind for use and makes it into a 
                tuple.
                """
                for tree in line[1]:
                    # convert the minikind to kind
                    tree[0] = self._minikind_to_kind[tree[0]]
                    # convert the size to an int
                    tree[2] = int(tree[2])
                    tree[3] = tree[3] == 'y'
                return line[0], map(tuple, line[1])
            new_entries = map(_line_to_entry, entries)
            self._entries_to_current_state(new_entries)
            self._dirblock_state = DirState.IN_MEMORY_UNMODIFIED

    def _read_header(self):
        """This reads in the metadata header, and the parent ids.

        After reading in, the file should be positioned at the null
        just before the start of the first record in the file.

        :return: (expected adler checksum, number of entries, parent list)
        """
        self._read_prelude()
        parent_line = self._state_file.readline()
        info = parent_line.split('\0')
        num_parents = int(info[0])
        assert num_parents == len(info)-2, 'incorrect parent info line'
        self._parents = info[1:-1]

        ghost_line = self._state_file.readline()
        info = ghost_line.split('\0')
        num_ghosts = int(info[1])
        assert num_ghosts == len(info)-3, 'incorrect ghost info line'
        self._ghosts = info[2:-1]
        self._header_state = DirState.IN_MEMORY_UNMODIFIED

    def _read_header_if_needed(self):
        """Read the header of the dirstate file if needed."""
        if self._header_state == DirState.NOT_IN_MEMORY:
            self._read_header()

    def _read_prelude(self):
        """Read in the prelude header of the dirstate file

        This only reads in the stuff that is not connected to the adler
        checksum. The position will be correct to read in the rest of
        the file and check the checksum after this point.
        The next entry in the file should be the number of parents,
        and their ids. Followed by a newline.
        """
        header = self._state_file.readline()
        assert header == '#bazaar dirstate flat format 2\n', \
            'invalid header line: %r' % (header,)
        adler_line = self._state_file.readline()
        assert adler_line.startswith('adler32: '), 'missing adler32 checksum'
        self.adler_expected = int(adler_line[len('adler32: '):-1])
        num_entries_line = self._state_file.readline()
        assert num_entries_line.startswith('num_entries: '), 'missing num_entries line'
        self._num_entries = int(num_entries_line[len('num_entries: '):-1])
    
    def save(self):
        """Save any pending changes created during this session.
        
        We reuse the existing file, because that prevents race conditions with
        file creation, and we expect to be using oslocks on it in the near 
        future to prevent concurrent modification and reads - because dirstates
        incremental data aggretation is not compatible with reading a modified
        file, and replacing a file in use by another process is impossible on 
        windows.

        A dirstate in read only mode should be smart enough though to validate
        that the file has not changed, and otherwise discard its cache and
        start over, to allow for fine grained read lock duration, so 'status'
        wont block 'commit' - for example.
        """
        if (self._header_state == DirState.IN_MEMORY_MODIFIED or
            self._dirblock_state == DirState.IN_MEMORY_MODIFIED):
            self._state_file.seek(0)
            self._state_file.writelines(self.get_lines())
            self._state_file.truncate()
            self._state_file.flush()
            self._header_state = DirState.IN_MEMORY_UNMODIFIED
            self._dirblock_state = DirState.IN_MEMORY_UNMODIFIED

    def _set_data(self, parent_ids, root_entries, dirblocks):
        """Set the full dirstate data in memory.

        This is an internal function used to completely replace the objects
        in memory state. It puts the dirstate into state 'full-dirty'.

        :param parent_ids: A list of parent tree revision ids.
        :param root_entrie: The root entries: A list of entries, one per fileid found
            at the root.
        :param dirblocks: A list containing one tuple for each directory in the
            tree. Each tuple contains the directory path and a list of entries 
            found in that directory.
        """
        # our memory copy is now authoritative.
        self._dirblocks = dirblocks
        self._root_entries = root_entries
        self._header_state = DirState.IN_MEMORY_MODIFIED
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED
        self._parents = list(parent_ids)

    def set_path_id(self, path, new_id):
        """Change the id of path to new_id in the current working tree.

        :param path: The path inside the tree to set - '' is the root, 'foo'
            is the path foo in the root.
        :param new_id: The new id to assign to the path. If unicode, it will
            be encoded to utf8. In future this will be deprecated: avoid using
            unicode ids if possible.
        """
        # TODO: start warning here.
        if new_id.__class__ == unicode:
            new_id = new_id.encode('utf8')
        self._read_dirblocks_if_needed()
        if len(path):
            import pdb;pdb.set_trace()
            # logic not written
            raise NotImplementedError(self.set_path_id)
        # TODO: check new id is unique
        entry = self._get_entry(0, path_utf8='')
        # TODO: version of _get_block_entry_index that works with the root so
        # we dont look up this twice.
        index = self._root_entries.index(entry)
        if new_id == entry[0][2]:
            # no change
            return
        if len(entry[1]) > 1:
            # TODO: split the record.
            raise NotImplementedError(self.set_path_id)
            root_info, root_parents = self._root_entrie
            if len(root_parents):
                self.add_deleted(root_info[3], root_parents)
        # replace the entry:
        self._root_entries[index] = (('', '', new_id), entry[1])
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED

    def set_parent_trees(self, trees, ghosts):
        """Set the parent trees for the dirstate.

        :param trees: A list of revision_id, tree tuples. tree must be provided
            even if the revision_id refers to a ghost: supply an empty tree in 
            this case.
        :param ghosts: A list of the revision_ids that are ghosts at the time
            of setting.
        """ 
        # TODO: generate a list of parent indexes to preserve to save 
        # processing specific parent trees. In the common case one tree will
        # be preserved - the left most parent.
        # TODO: if the parent tree is a dirstate, we might want to walk them
        # all by path in parallel for 'optimal' common-case performance.
        # generate new root row.
        self._read_dirblocks_if_needed()
        old_roots = self._root_entries
        root_info = self._root_entries[0]
        new_parent_count = len(trees)
        # TODO future sketch: Examine the existing parents to generate a change
        # map and then walk the new parent trees only, mapping them into the
        # dirstate. Walk the dirstate at the same time to remove unreferenced
        # entries.
        # for now: 
        # sketch: loop over all entries in the dirstate, cherry picking 
        # entries from the parent trees, if they are not ghost trees.
        # after we finish walking the dirstate, all entries not in the dirstate
        # are deletes, so we want to append them to the end as per the design
        # discussions. So do a set difference on ids with the parents to
        # get deletes, and add them to the end.
        # During the update process we need to answer the following questions:
        # - find other keys containing a fileid in order to create cross-path
        #   links. We dont't trivially use the inventory from other trees
        #   because this leads to either double touching, or to accessing
        #   missing keys,
        # - find other keys containing a path 
        # We accumulate each entry via this dictionary, including the root 
        by_path = {}
        id_index = {}
        # we could do parallel iterators, but because file id data may be
        # scattered throughout, we dont save on index overhead: we have to look
        # at everything anyway. We can probably save cycles by reusing parent
        # data and doing an incremental update when adding an additional
        # parent, but for now the common cases are adding a new parent (merge),
        # and replacing completely (commit), and commit is more common: so
        # optimise merge later.
        
        # ---- start generation of full tree mapping data
        # what trees should we use?
        parent_trees = [tree for rev_id, tree in trees if rev_id not in ghosts]
        # how many trees do we end up with 
        parent_count = len(parent_trees)

        # one: the current tree
        for entry in self._iter_entries():
            # skip entries not in the current tree
            if entry[1][0][0] in ('absent', 'relocated'):
                continue
            by_path[entry[0]] = [entry[1][0]] + \
                [DirState.NULL_PARENT_DETAILS] * parent_count
            id_index[entry[0][2]] = set([entry[0]])
        
        # now the parent trees:
        for tree_index, tree in enumerate(parent_trees):
            # the index is off by one, adjust it.
            tree_index = tree_index + 1
            # when we add new locations for a fileid we need these ranges for
            # any fileid in this tree as we set the by_path[id] to:
            # already_processed_tree_details + new_details + new_location_suffix
            # the suffix is from tree_index+1:parent_count+1.
            new_location_suffix = [DirState.NULL_PARENT_DETAILS] * (parent_count - tree_index)
            # now stitch in all the entries from this tree
            for path, entry in tree.inventory.iter_entries_by_dir():
                # here we process each trees details for each item in the tree.
                # we first update any existing entries for the id at other paths,
                # then we either create or update the entry for the id at the
                # right path, and finally we add (if needed) a mapping from
                # file_id to this path. We do it in this order to allow us to
                # avoid checking all known paths for the id when generating a
                # new entry at this path: by adding the id->path mapping last,
                # all the mappings are valid and have correct relocation
                # records where needed. 
                file_id = entry.file_id.encode('utf8')
                path_utf8 = path.encode('utf8')
                dirname, basename = os.path.split(path_utf8)
                new_entry_key = (dirname, basename, file_id)
                # tree index consistency: All other paths for this id in this tree
                # index must point to the correct path.
                for entry_key in id_index.setdefault(file_id, set()):
                    # TODO:PROFILING: It might be faster to just update
                    # rather than checking if we need to, and then overwrite
                    # the one we are located at.
                    if entry_key != new_entry_key:
                        # this file id is at a different path in one of the
                        # other trees, so put absent pointers there
                        # This is the vertical axis in the matrix, all pointing
                        # tot he real path.
                        by_path[entry_key][tree_index] = ('relocated', path_utf8, 0, False, '')
                # by path consistency: Insert into an existing path record (trivial), or 
                # add a new one with relocation pointers for the other tree indexes.
                if new_entry_key in id_index[file_id]:
                    # there is already an entry where this data belongs, just insert it.
                    by_path[new_entry_key][tree_index] = \
                        self._inv_entry_to_details(entry)
                else:
                    # add relocated entries to the horizontal axis - this row
                    # mapping from path,id. We need to look up the correct path
                    # for the indexes from 0 to tree_index -1
                    new_details = []
                    for lookup_index in xrange(tree_index):
                        # boundary case: this is the first occurence of file_id
                        # so there are no id_indexs, possibly take this out of
                        # the loop?
                        if not len(id_index[file_id]):
                            new_details.append(DirState.NULL_PARENT_DETAILS)
                        else:
                            # grab any one entry, use it to find the right path.
                            # TODO: optimise this to reduce memory use in highly 
                            # fragmented situations by reusing the relocation
                            # records.
                            a_key = iter(id_index[file_id]).next()
                            if by_path[a_key][lookup_index][0] in ('relocated', 'absent'):
                                # its a pointer or missing statement, use it as is.
                                new_details.append(by_path[a_key][lookup_index])
                            else:
                                # we have the right key, make a pointer to it.
                                real_path = ('/'.join(a_key[0:2])).strip('/')
                                new_details.append(('relocated', real_path, 0, False, ''))
                    new_details.append(self._inv_entry_to_details(entry))
                    new_details.extend(new_location_suffix)
                    by_path[new_entry_key] = new_details
                    id_index[file_id].add(new_entry_key)
        # --- end generation of full tree mappings

        # sort and output all the entries
        new_entries = sorted(by_path.items())
        self._entries_to_current_state(new_entries)
        self._parents = [rev_id for rev_id, tree in trees]
        self._ghosts = list(ghosts)
        self._header_state = DirState.IN_MEMORY_MODIFIED
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED

    def set_state_from_inventory(self, new_inv):
        """Set new_inv as the current state. 

        This API is called by tree transform, and will usually occur with
        existing parent trees.

        :param new_inv: The inventory object to set current state from.
        """
        self._read_dirblocks_if_needed()
        # sketch:
        #  generate a byid index of the dirstate
        id_index = {}
        for key, tree_details in self._iter_entries():
            id_index.setdefault(key[2], set()).add(key)

        num_present_parents = len(self._parents) - len(self._ghosts)
        # incremental algorithm:
        # two iterators: current data and new data, both in dirblock order. 
        new_iterator = new_inv.iter_entries_by_dir()
        # we will be modifying the dirstate, so we need a stable iterator. In future we might write one, for now we just clone the state into a list
        old_iterator = iter(list(self._iter_entries()))
        # both must have roots so this is safe:
        current_new = new_iterator.next()
        current_old = old_iterator.next()
        def advance(iterator):
            try:
                return old_iterator.next()
            except StopIteration:
                return None
        while current_new or current_old:
            # skip entries in old that are not really there
            if current_old and current_old[1][0] in ('relocated', 'absent'):
                current_old = advance(old_iterator)
                continue
            if current_new:
                # convert new into dirblock style
                new_dirname, new_basename = os.path.split(current_new[0].encode('utf8'))
                new_id = current_new[1].file_id.encode('utf8')
                new_entry_key = (new_dirname, new_basename, new_id)
            # 5 cases, we dont have a value that is strictly greater than everything, so
            # we make both end conditions explicit
            if not current_old:
                # old is finished: insert current_new into the state.
                self.update_minimal(new_entry_key, current_new[1].kind,
                    executable=current_new[1].executable, id_index=id_index)
                current_new = advance(new_iterator)
            elif not current_new:
                # new is finished
                import pdb;pdb.set_trace()
            elif new_entry_key == current_old[0]:
                # same -  common case
                # TODO: update the record if anything significant has changed.
                # the minimal required trigger is if the execute bit has
                # changed.
                if current_old[1][0][3] != current_new[1].executable:
                    import pdb;pdb.set_trace()
                # both sides are dealt with, move on
                current_old = advance(old_iterator)
                current_new = advance(new_iterator)
            elif new_entry_key < current_old[0]:
                # new comes before 
                import pdb;pdb.set_trace()
            else:
                # old comes before:
                # remove old from the state, advance old
                # to remove old, we have two conditions.
                # either its the last reference to this path that we are
                # removing, or its not. If its the last reference, we remove
                # the entire row and remove the path from the id mapping. If
                # its not the last reference, we just set it to absent.
                last_reference = True
                for lookup_index in xrange(1, num_present_parents + 1):
                    if current_old[1][lookup_index] not in ('absent', 'relocated'):
                        last_reference = False
                        break
                if not last_reference:
                    import pdb;pdb.set_trace()
                    # common case, theres a parent at this path
                    current_old[1][0] = DirState.NULL_PARENT_DETAILS
                else:
                    # there are no more references at this path
                    id_index[current_old[0][2]].remove(current_old[0])
                    # are there others (which will need to be changed
                    # from relocated to absent for index 0)?
                    if len(id_index[current_old[0][2]]):
                        import pdb;pdb.set_trace()
                    block = self._find_block(current_old[0])
                    entry_index, present = self._find_entry_index(key, block)
                    assert present
                    block.pop(entry_index)
                current_old = advance(old_iterator)
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED

    def update_minimal(self, key, kind, executable=False, fingerprint='',
        packed_stat=None, size=0, id_index=None):
        """Update an entry to the state in tree 0."""
        self._read_dirblocks_if_needed()
        if key[0:2] == ('', ''):
            block = self._root_entries
        else:
            block = self._find_block(key)[1]
        if packed_stat is None:
            packed_stat = DirState.NULLSTAT
        entry_index, present = self._find_entry_index(key, block)
        new_details = (kind, fingerprint, size, executable, packed_stat)
        if not present:
            # new entry, synthesis cross reference here,
            assert id_index, 'need an id index to generate a new entry'
            existing_keys = id_index.setdefault(key, set())
            if not existing_keys:
                # not currently in the state, simplest case
                new_entry = key, [new_details] + self._empty_parent_info()
            else:
                import pdb;pdb.set_trace()

            block.insert(entry_index, new_entry)
            existing_keys.add(key)
        else:
            # Does the new state matter? 
            import pdb;pdb.set_trace()
            block[entry_index][1][0] = new_details
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED



def pack_stat(st, _encode=base64.encodestring, _pack=struct.pack):
    """Convert stat values into a packed representation."""
    # jam 20060614 it isn't really worth removing more entries if we
    # are going to leave it in packed form.
    # With only st_mtime and st_mode filesize is 5.5M and read time is 275ms
    # With all entries filesize is 5.9M and read time is mabye 280ms
    # well within the noise margin

    # base64.encode always adds a final newline, so strip it off
    return _encode(_pack('>llllll'
        , st.st_size, st.st_mtime, st.st_ctime
        , st.st_dev, st.st_ino, st.st_mode))[:-1]

