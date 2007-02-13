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

Pseduo EBNF grammar for the disk format:
MINIKIND = "f" | "d" | "l";
NL = "\n";
NULL = "\0";
WHOLE NUMBER = {digit}, digit;

dirstate format = header line, full checksum, row count, parent details,
 ghost_details, rows;
header line = "#bazaar dirstate flat format 1", NL;
full checksum = "adler32: ", ["-"], WHOLE NUMBER, NL;
row count = "num_entries: ", digit, NL;
parent_details = WHOLE NUMBER, NULL, NL; XXX: complete this line
ghost_details = WHOLE NUMBER, NULL, {GHOST_ID NULL}*, NL;
rows = dirname, NULL, basename, NULL, MINIKIND, NULL, fileid_utf8, NULL,
    WHOLE NUMBER (* size *), NULL, packed stat, NULL, sha1|symlink target, 
    {PARENT ROW}
PARENT ROW = NULL, revision_utf8, NULL, MINIKIND, NULL, dirname, NULL,
    basename, NULL, WHOLE NUMBER (* size *), NULL, "y" | "n", NULL,
    SHA1

PARENT ROW's are emitted for every parent that is not in the ghosts details
line. That is, if the parents are foo, bar, baz, and the ghosts are bar, then
each row will have a PARENT ROW for foo and baz, but not for bar.

----

Design priorities:
 1) Fast end to end use for bzr's top 5 uses cases.
 2) fall back current object model as needed.
 3) scale usably to the largest trees known today - say 50K entries.


Locking:
 Eventually reuse dirstate objects across locks IFF the dirstate file has not
 been modified, but will require that we flush/ignore cached stat-hit data
 because we wont want to restat all files on disk just because a lock was
 acquired, yet we cannot trust the data after the previous lock was released.

Memory representation:
 vecter of all directories, and vector of the childen ?
   i.e. 
     root_row = (direntry for root, [parent_direntries_for_root]), 
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
from bzrlib.osutils import pathjoin, sha_file, sha_string, walkdirs


class DirState(object):
    """Record directory and metadata state for fast access.

    A dirstate is a specialised data structure for managing local working
    tree state information. Its not yet well defined whether it is platform
    specific, and if it is how we detect/parameterise that.
    """

    _kind_to_minikind = {'file':'f', 'directory':'d', 'symlink':'l'}
    _minikind_to_kind = {'f':'file', 'd':'directory', 'l':'symlink'}
    _to_yesno = {True:'y', False: 'n'} # TODO profile the performance gain
     # of using int conversion rather than a dict here. AND BLAME ANDREW IF
     # it is faster.

    NOT_IN_MEMORY = 0
    IN_MEMORY_UNMODIFIED = 1
    IN_MEMORY_MODIFIED = 2

    NULLSTAT = 'x' * 32

    def __init__(self):
        """Create a  DirState object.

        Attributes of note:

        :attr _root_row: The root row of the directory/file information,
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
        self._root_row = None
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
        self._read_dirblocks_if_needed()
        utf8path = path.encode('utf8')
        dirname, basename = os.path.split(utf8path)
        block_index = bisect.bisect_left(self._dirblocks, (dirname, []))
        if (block_index == len(self._dirblocks) or
            self._dirblocks[block_index][0] != dirname):
            # some parent path has not been added - its an error to add this
            # child
            raise errors.NoSuchFile(path)
        block = self._dirblocks[block_index][1]
        if kind == 'file':
            row_data = ((dirname, basename, kind, file_id.encode('utf8'),
                stat.st_size, pack_stat(stat), link_or_sha1), [])
        elif kind == 'directory':
            row_data = ((dirname, basename, kind, file_id.encode('utf8'),
                0, pack_stat(stat), ''), [])
        elif kind == 'symlink':
            row_data = ((dirname, basename, kind, file_id.encode('utf8'),
                stat.st_size, pack_stat(stat), link_or_sha1), [])
        else:
            raise errors.BzrError('unknown kind %r' % kind)
        row_index = bisect.bisect_left(block, row_data)
        if len(block) > row_index:
            assert block[row_index][1] != basename, \
                "basename %r already added" % basename
        block.insert(row_index, row_data)

        if kind == 'directory':
           # insert a new dirblock
           bisect.insort_left(self._dirblocks, (utf8path, []))
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED

    def add_parent_tree(self, tree_id, tree):
        """Add tree as a parent to this dirstate."""
        self._read_dirblocks_if_needed()
        self._parents.append(tree_id)
        self._header_state = DirState.IN_MEMORY_MODIFIED
        if tree is None:
            self._ghosts.append(tree_id)

    @staticmethod
    def from_tree(tree, dir_state_filename):
        """Create a dirstate from a bzr Tree.

        :param tree: The tree which should provide parent information and
            inventory ids.
        """
        # XXX: aka the big ugly.
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

        # FIXME: is this utf8 safe?

        to_minikind = DirState._kind_to_minikind
        to_yesno = DirState._to_yesno

        st = os.lstat(tree.basedir)
        root_info = (
            '', '' # No path
            , 'directory', tree.inventory.root.file_id.encode('utf8')
            , 0 # no point having a size for dirs.
            , pack_stat(st)
            , '' # No sha
            )
        root_parents = []
        for parent_tree in parent_trees:
            root_parents.append((
                    parent_tree.inventory.root.revision.encode('utf8'),
                    'directory', '',
                    '',
                    '',
                    False,
                    '',
                    ))
            
        root_row = (root_info, root_parents)
        dirblocks = []
        for dirinfo, block in tree.walkdirs():
            # dirinfo is path, id
            to_remove = []
            # add the row for this block
            block_row = []
            dirblocks.append((dirinfo[0], block_row))
            for relpath, name, kind, st, fileid, versionedkind in block:
                if fileid is None:
                    # unversioned file, skip
                    continue
                # TODO? factor out this loop body as a helper function ?
                s = None
                dirname, basename = os.path.split(relpath.encode('utf8'))
                if kind == 'file':
                    s = tree.get_file_sha1(fileid, relpath)
                elif kind == 'directory':
                    if name in ('.bzr', '.hg', 'CVS', '.svn', '_svn'):
                        raise Exception('skipping dirs not supported yet')
                        # Skip this, and all children
                        to_remove.append((relpath, name, kind, st, abspath))
                        continue
                    # no sha value
                    s = ''
                elif kind == 'symlink':
                    # sha value of the link target ?!
                    s = os.readlink(abspath)
                parent_info = []
                for count in xrange(num_parents):
                    parent_info.append(
                        result._parent_info(parent_trees[count], fileid))
                row_data = (dirname.encode('utf8'), basename.encode('utf8'),
                    kind, fileid.encode('utf8'), st.st_size, pack_stat(st),
                    s)
                block_row.append((row_data, parent_info))

            # It isn't safe to remove entries while we are iterating
            # over the same list, so remove them now
            for entry in to_remove:
                block.remove(entry)

        #lines.append(result._get_parents_line(parent_ids))
        #lines.append(result._get_ghosts_line([]))
        result._set_data(parent_ids, root_row, dirblocks)
        result.save()
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
        lines.extend(map(self._row_to_line, self._iter_rows()))
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
        return self._parents

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
        # a new root directory, with a pack_stat (the x's) that is just noise and will 
        # never match the output of base64 encode.
        root_row_data = ('', '', 'directory', bzrlib.inventory.ROOT_ID, 0,
            DirState.NULLSTAT, '')
        root_parents = []
        root_row = (root_row_data, root_parents)
        empty_tree_dirblocks = [('', [])] # root dir contents - no entries.
        result._set_data([], root_row, empty_tree_dirblocks)
        try:
            result.save()
        except:
            result._state_file.close()
            raise
        return result

    def _iter_rows(self):
        """Iterate over all the row data in the dirstate.

        Each yelt item is a tuple of (row_data, parent_data_list).
        """
        self._read_dirblocks_if_needed()
        yield self._root_row
        for directory in self._dirblocks:
            for row in directory[1]:
                yield row

    def _get_output_lines(self, lines):
        """format lines for final output.
        
        :param lines: A sequece of lines containing the parents list and the
            path lines.
        """
        output_lines = ['#bazaar dirstate flat format 1\n']
        lines.append('') # a final newline
        inventory_text = '\0\n\0'.join(lines)
        output_lines.append('adler32: %s\n' % (zlib.adler32(inventory_text),))
        # -3, 1 for num parents, 1 for ghosts, 1 for final newline
        num_entries = len(lines)-3
        output_lines.append('num_entries: %s\n' % (num_entries,))
        output_lines.append(inventory_text)
        return output_lines

    @staticmethod
    def on_file(path):
        """Construct a DirState on the file at path path."""
        result = DirState()
        result._state_file = open(path, 'rb+')
        return result

    def _parent_info(self, parent_tree, fileid):
        """Generate the parent information for file_id in parent_tree."""
        # FIXME: This is probably expensive - we encode the path that in the
        # common case will be the same across all parents, twice. 
        # also, id2path is slow in inventory, and we should make that fast.
        try:
            parent_entry = parent_tree.inventory[fileid]
        except errors.NoSuchId:
            # this parent does not have fileid - return a bogus entry, which 
            # will be filtered out on iteration etc.
            # an empty revision id is bogus and safe to put on disk
            # we make it be a 'file', just because. We give it the 
            # deleted file path dirname and basename, 0 size, not executable
            # and no sha1.
            return ('', 'file', '/', 'RECYCLED.BIN', 0, False, '')
        parent_path = parent_tree.inventory.id2path(fileid)
        dirname, basename = os.path.split(parent_path.encode('utf8'))
        return (parent_entry.revision.encode('utf8'),
            parent_entry.kind,
            # FIXME: set these from the parent
            dirname.encode('utf8'), basename.encode('utf8'),
            parent_entry.text_size or 0,
            parent_entry.executable,
            parent_entry.text_sha1 or '',
            )

    def _read_dirblocks_if_needed(self):
        """Read in all the dirblocks from the file if they are not in memory."""
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
            field_count = len(fields)
            # Each line now has an extra '\n' field which is not used
            # so we just skip over it
            # number of fields per dir_entry
            #  + number of fields per parent_entry
            #  + newline
            num_present_parents = len(self._parents) - len(self._ghosts)
            entry_size = 7 + (7 * (num_present_parents)) + 1
            expected_field_count = entry_size * self._num_entries
            # is the file too short ?
            assert field_count - cur == expected_field_count, \
                'field count incorrect %s != %s, entry_size=%s, '\
                'num_entries=%s fields=%r' % (
                    field_count - cur, expected_field_count, entry_size,
                    self._num_entries, fields)

            # Fast path the case where there are 1 or 2 parents
            if num_present_parents == 0:
                entries = [(fields[pos:pos+7], []) for pos in xrange(cur, field_count, entry_size)]
            elif num_present_parents == 1:
                entries = [(fields[pos:pos+7], [fields[pos+7:pos+14],])
                    for pos in xrange(cur, field_count, entry_size)]
            elif num_present_parents == 2:
                entries = [(fields[pos:pos+7], [
                            fields[pos+7:pos+14],
                            fields[pos+14:pos+21],])
                    for pos in xrange(cur, field_count, entry_size)]
            else:
                entries = [(
                    fields[pos:pos+7],
                    tuple([fields[chunk:chunk+7] for 
                        chunk in xrange(pos + 7, pos+entry_size-1, 7)]))
                            for pos in xrange(cur, field_count, entry_size)
                ]

            assert len(entries) == self._num_entries, '%s != %s entries' % (len(entries),
                self._num_entries)

            def _line_to_row(line):
                """Convert a freshly read line's size and minikind for use."""
                # convert the minikind to kind
                line[0][2] = self._minikind_to_kind[line[0][2]]
                # convert the size to an int
                line[0][4] = int(line[0][4])
                for parent in line[1]:
                    parent[1] = self._minikind_to_kind[parent[1]]
                    parent[4] = int(parent[4])
                    parent[5] = parent[5] == 'y'
                return tuple(line[0]), map(tuple, line[1])
            new_rows = map(_line_to_row, entries)
            self._rows_to_current_state(new_rows)
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
        self._parents = [p.decode('utf8') for p in info[1:-1]]

        ghost_line = self._state_file.readline()
        info = ghost_line.split('\0')
        num_ghosts = int(info[1])
        assert num_ghosts == len(info)-3, 'incorrect ghost info line'
        self._ghosts = [p.decode('utf8') for p in info[2:-1]]
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
        assert header == '#bazaar dirstate flat format 1\n', \
            'invalid header line: %r' % (header,)
        adler_line = self._state_file.readline()
        assert adler_line.startswith('adler32: '), 'missing adler32 checksum'
        self.adler_expected = int(adler_line[len('adler32: '):-1])
        num_entries_line = self._state_file.readline()
        assert num_entries_line.startswith('num_entries: '), 'missing num_entries line'
        self._num_entries = int(num_entries_line[len('num_entries: '):-1])
    
    def _row_to_line(self, row):
        """Serialize row to a NULL delimited line ready for _get_output_lines.
        
        :param row: A row_tuple as defined in the module docstring.
        """
        entire_row = list(row[0])
        for parent_number, parent_data in enumerate(row[1]):
            # (revision, kind, dirname, basename, size, executable_bool, sha1)
            entire_row.extend(parent_data)
            # minikind conversion of the parent
            parent_offset = 7 + parent_number * 7
            entire_row[parent_offset + 1] = DirState._kind_to_minikind[parent_data[1]]
            entire_row[parent_offset + 4] = str(parent_data[4])
            entire_row[parent_offset + 5] = DirState._to_yesno[parent_data[5]]
        # conversion from memory to disk-ready format:
        # minikind conversion of the current row type.
        entire_row[2] = DirState._kind_to_minikind[entire_row[2]]
        entire_row[4] = str(entire_row[4])
        # minikind of parents
        return '\0'.join(entire_row)

    def _rows_to_current_state(self, new_rows):
        """Load new_rows into self._root_row and self.dirblocks.

        Process new_rows into the current state object, making them the active
        state.

        :param new_rows: A sorted list of rows. This function does not sort
            to prevent unneeded overhead when callers have a sorted list
            already.
        :return: Nothing.
        """
        assert new_rows[0][0][0:2] == ('', ''), \
            "Incorrect root row %r" % new_rows[0][0]
        self._root_row = new_rows[0]
        self._dirblocks = [('', [])]
        for row in new_rows[1:]:
            if row[0] != self._dirblocks[-1][0]:
                # new block
                self._dirblocks.append((row[0][0], []))
            # append the row to the current block
            self._dirblocks[-1][1].append(row)
    
    def save(self):
        """Save any pending changes created during this session."""
        if (self._header_state == DirState.IN_MEMORY_MODIFIED or
            self._dirblock_state == DirState.IN_MEMORY_MODIFIED):
            self._state_file.seek(0)
            self._state_file.writelines(self.get_lines())
            self._state_file.flush()
            self._state_file.truncate()
            self._header_state = DirState.IN_MEMORY_UNMODIFIED
            self._dirblock_state = DirState.IN_MEMORY_UNMODIFIED

    def _set_data(self, parent_ids, root_row, dirblocks):
        """Set the full dirstate data in memory.

        This is an internal function used to completely replace the objects
        in memory state. It puts the dirstate into state 'full-dirty'.

        :param parent_ids: A list of parent tree revision ids.
        :param root_row: The root row - a tuple of the root direntry and the
            list of matching direntries from the parent_ids trees.
        :param dirblocks: A list containing one tuple for each directory in the
            tree. Each tuple contains the directory path and a list of
            row data in the same format as root_row.
        """
        # our memory copy is now authoritative.
        self._dirblocks = dirblocks
        self._root_row = root_row
        self._header_state = DirState.IN_MEMORY_MODIFIED
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED
        self._parents = list(parent_ids)

    def set_path_id(self, path, new_id):
        """Change the id of path to new_id.

        :param path: The path inside the tree to set - '' is the root, 'foo'
            is the path foo in the root.
        :param new_id: The new id to assign to the path. If unicode, it will
            be encoded to utf8. In future this will be deprecated: avoid using
            unicode ids if possible.
        """
        self._read_header_if_needed()
        if len(path) or len(self._parents):
            # logic not written
            raise NotImplementedError(self.set_path_id)
        self._read_dirblocks_if_needed()
        if new_id.__class__ == unicode:
            new_id = new_id.encode('utf8')
        root_info, root_parents = self._root_row
        self._root_row = (root_info[0:3] + (new_id, ) + root_info[4:7]), root_parents
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
        old_root = self._root_row
        root_info = self._root_row[0]
        new_parent_count = len(trees)
        # sketch: loop over all rows in the dirstate, cherry picking 
        # entries from the parent trees, if they are not ghosts.
        # after we finish walking the dirstate, all entries not in the dirstate
        # are deletes, so we want to append them to the end as per the design
        # discussions. So do a set difference on ids with the parents to
        # get deletes, and add them to the end.
        new_rows = []
        # skip ghost trees, as they dont get represented.
        parent_trees = [tree for rev_id, tree in trees if rev_id not in ghosts]
        parent_tree_count = len(parent_trees)
        # loop over existing entries in the dirstate.
        checked_ids = set()
        for entry, old_parents in self._iter_rows():
            file_id = entry[3]
            checked_ids.add(file_id)
            new_parents = [None] * parent_tree_count
            for position, parent_tree in enumerate(parent_trees):
                # revision_utf8, KIND, dirname, basename, size, executable, sha
                new_parents[position] = self._parent_info(parent_tree, file_id)
            assert None not in new_parents
            new_rows.append((entry, new_parents))
        # get additional ids that are present in parents and not in this tree.
        deleted_ids = set()
        for tree in parent_trees:
            deleted_ids.update(set(tree.inventory._byid).difference(checked_ids))
        # add the deleted ids to the dirstate. deleted files are represented as
        # a file with dirname '', basename ''
        for file_id in deleted_ids:
            # add these ids to the deleted block
            checked_ids.add(file_id)
            # deleted items have a synthetic entry.
            entry = ('/', 'RECYCLED.BIN', 'file', file_id.encode('utf8'), 0,
                DirState.NULLSTAT, '')
            new_parents = [None] * parent_tree_count
            for position, parent_tree in enumerate(parent_trees):
                # revision_utf8, KIND, dirname, basename, size, executable, sha
                new_parents[position] = self._parent_info(parent_tree, file_id)
            assert None not in new_parents
            new_rows.append((entry, new_parents))

        # sort all the rows
        new_rows = sorted(new_rows)
        self._rows_to_current_state(new_rows)
        self._parents = [rev_id for rev_id, tree in trees]
        self._ghosts = list(ghosts)
        self._header_state = DirState.IN_MEMORY_MODIFIED
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED

    def set_state_from_inventory(self, new_inv):
        """Set new_inv as the current state. 

        :param new_inv: The inventory object to set current state from.
        """
        self._read_dirblocks_if_needed()
        # sketch:
        #  generate a byid index of the dirstate
        parent_rows = {}
        for row, parents in self._iter_rows():
            parent_rows[row[3]] = parents
        #  walk the new inventory in directory order, copying parent data
        #    from the id index
        new_rows = []
        for path, entry in new_inv.iter_entries_by_dir():
            dirname, basename = os.path.split(path.encode('utf8'))
            kind = entry.kind
            fileid_utf8 = entry.file_id.encode('utf8')
            if kind == 'file':
                size = entry.text_size or 0
                sha1 = entry.text_sha1 or ''
            elif kind == 'symlink':
                size = 0
                sha1 = (entry.symlink_target or '').encode('utf8')
            else:
                size = 0
                sha1 = ''
            try:
                parents = parent_rows[fileid_utf8]
                del parent_rows[fileid_utf8]
            except KeyError:
                parents = []
            new_row = (dirname, basename, kind, fileid_utf8, size, DirState.NULLSTAT, sha1), parents
            new_rows.append(new_row)
        #  append deleted data to the end of the tree as usual.
        for fileid_utf8, parents in parent_rows.items():
            if not parents:
                # this row was only present in the old state, had no parents
                continue
            # deleted items have a synthetic entry.
            new_row = ('/', 'RECYCLED.BIN', 'file', fileid_utf8, 0,
                DirState.NULLSTAT, ''), parents
            new_rows.append(new_row)

        # sort all the rows (the ones in parents not in current may be unsorted)
        new_rows = sorted(new_rows)
        self._rows_to_current_state(new_rows)
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

