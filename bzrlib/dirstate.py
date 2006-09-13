# Copyright (C) 2006 by Canonical Ltd
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
 rows;
header line = "#bazaar dirstate flat format 1", NL;
full checksum = "adler32: ", ["-"], WHOLE NUMBER, NL;
row count = "num_entries: ", digit, NL;
parent_details = WHOLE NUMBER, NULL, NL; XXX: complete this line
rows = dirname, NULL, basename, NULL, MINIKIND, NULL, fileid_utf8, NULL,
    WHOLE NUMBER (* size *), NULL, packed stat, NULL, symlink value, 
    {PARENT ROW}
PARENT ROW = NULL, revision_utf8, NULL, MINIKIND, NULL, dirname, NULL,
    basename, NULL, WHOLE NUMBER (* size *), NULL, "y" | "n", NULL,
    SHA1

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

DirState State machines? Strategy needed ?
 We have a number of key states:
  A memory object exists, disk data untouched.
  B have read just the parents details to answer common queries
  C have read the entire dirstate, so can answer questions about the tree
    from memory
  D have altered some part of the directory data, can incrementally save.
    i.e. have refreshed a stat hit for a single file.
  E (full-dirty) have altered some part of the directory data, cannot
  incrementally save.  I.e. have added or deleted a file, or added or deleted
  parents to the dirstate itself.

 currently _header_read = True means the header is read, can be in B through E
           _clean = True means the in memory representation is exactly whats
                    on disk - C
           _clean = False -> A or B or D or E
           _header_read = False means A

Memory representation:
Each row will be a tuple that has:
 current_row_data_tuple, parent_list
current_row_data = [dirname, basename, fullkind, fileid, size, packed-stat, linkvalue]
parents_list = [(revision, kind, dirname, basename, size, executable_bool, sha1) ...]
row = (current_data, parents_list)

Still need to address how rows are managed:
open questions:
 vector of all rows or one vector per directory ?
 vector of all rows allows trivial bisection to find paths
 vecter of all directories, and vector of the childen ?
   i.e. 
     (data for root), 
     [
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

import bzrlib.inventory
from bzrlib.osutils import pathjoin, sha_file, sha_string, walkdirs

# TODO:
# 1)

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

    def __init__(self):
        self._header_read = False
        self._clean = False
        self._parents = []

    def add_parent_tree(self, tree_id, tree):
        """Add tree as a parent to this dirstate."""
        self._parents.append(tree_id)
        self._clean = False

    @staticmethod
    def from_tree(tree):
        """Create a dirstate from a bzr Tree.

        :param tree: The tree which should provide parent information and
            inventory ids.
        """
        result = DirState()

        lines = []

        _encode = base64.encodestring

        parent_ids = tree.get_parent_ids()
        num_parents = len(parent_ids)
        if num_parents > 3:
            raise ValueError('Cannot handle more than 3 parents')

        parent_trees = []
        for parent_id in parent_ids:
            parent_trees.append(tree.branch.repository.revision_tree(parent_id))

        lines.append(result._get_parents_line(parent_ids))
        # FIXME: is this utf8 safe?

        to_minikind = DirState._kind_to_minikind
        to_yesno = DirState._to_yesno

        st = os.lstat(tree.basedir)
        null_parent_info = '\0'.join((
                    'null:'
                    , '', ''
                    , ''
                    , ''
                    , ''
                    , ''
                    ))
            #, 'd', gen_root_id().encode('utf8')
        root_info = [
            '', '' # No path
            , 'd', tree.inventory.root.file_id.encode('utf8')
            , str(st.st_size)
            , pack_stat(st)
            , '' # No sha
            ] + [null_parent_info]*num_parents
#       disabled because the root entry has no revision attribute set.
#        for parent_tree in parent_trees:
#            root_info.append('\0'.join((
#                    parent_tree.inventory.root.revision.encode('utf8'),
#                    '', '',
#                    '',
#                    '',
#                    '',
#                    '',
#                    )))
            
        lines.append('\0'.join(root_info))

        for dirinfo, block in tree.walkdirs():

            to_remove = []
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
                    parent_entry = parent_trees[count].inventory[fileid]
                    parent_info.append(
                        (parent_entry.revision.encode('utf8'),
                         parent_entry.kind,
                         # FIXME: set these from the parent
                         dirname.encode('utf8'), basename.encode('utf8'),
                         parent_entry.text_size,
                         parent_entry.executable,
                         parent_entry.text_sha1,
                         ))
                row_data = (dirname.encode('utf8'), basename.encode('utf8'),
                    kind, fileid.encode('utf8'), st.st_size, pack_stat(st),
                    s)
                row_tuple = (row_data, parent_info)
                lines.append(result._row_to_line(row_tuple))

            # It isn't safe to remove entries while we are iterating
            # over the same list, so remove them now
            for entry in to_remove:
                block.remove(entry)

        result.lines = result._get_output_lines(lines)
        result._header_read = True
        result._clean = True
        return result

    def get_lines(self):
        """Serialise the entire dirstate to a sequence of lines."""
        if self._clean:
            return self.lines
        lines = []
        lines.append(self._get_parents_line(self.get_parent_ids()))
        # append the root line which is special cased
        lines.append(self._row_to_line(self._root_row))
        self.lines = self._get_output_lines(lines)
        return self.lines

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
        # This constructs a new DirState object on a path, sets the state_file
        # to a new empty file for that path. It then calls _set_data() with our
        # stock empty dirstate information - a root with ROOT_ID, no children,
        # and no parents. Finally it calls save() to ensure that this data will
        # persist.
        result = DirState()
        result.state_file = open(path, 'wb+')
        # a new root directory, with a pack_stat that is just noise and will 
        # never match the output of base64 encode.
        root_row_data = ('', '', 'directory', bzrlib.inventory.ROOT_ID, 0, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '')
        root_parents = []
        root_row = (root_row_data, root_parents)
        empty_tree_data = [('', [])] # root dir contents - no entries.
        result._set_data(root_row, empty_tree_data)
        try:
            result.save()
        except:
            result.state_file.close()
            raise
        return result

    def _get_output_lines(self, lines):
        """format lines for final output.
        
        :param lines: A sequece of lines containing the parents list and the
            path lines.
        """
        output_lines = ['#bazaar dirstate flat format 1\n']
        lines.append('') # a final newline
        inventory_text = '\0\n\0'.join(lines)
        output_lines.append('adler32: %s\n' % (zlib.adler32(inventory_text),))
        # -2, 1 for num parents, 1 for final newline
        num_entries = len(lines)-2
        output_lines.append('num_entries: %s\n' % (num_entries,))
        output_lines.append(inventory_text)
        return output_lines

    @staticmethod
    def on_file(path):
        """Construct a DirState on the file at path path."""
        result = DirState()
        result.state_file = open(path, 'rb+')
        return result

    def _read_all(self):
        """Read the entire state."""
        self._read_header()
        
    def _read_header(self):
        """This reads in the metadata header, and the parent ids.

        After reading in, the file should be positioned at the null
        just before the start of the first record in the file.

        :return: (expected adler checksum, number of entries, parent list)
        """
        self._read_prelude()
        parent_line = self.state_file.readline()
        info = parent_line.split('\0')
        num_parents = int(info[0])
        assert num_parents == len(info)-2, 'incorrect parent info line'

        self._parents = [p.decode('utf8') for p in info[1:-1]]

    def _read_header_if_needed(self):
        """Read the header of the dirstate file if needed."""
        if self._header_read is False:
            self._read_header()

    def _read_prelude(self):
        """Read in the prelude header of the dirstate file

        This only reads in the stuff that is not connected to the adler
        checksum. The position will be correct to read in the rest of
        the file and check the checksum after this point.
        The next entry in the file should be the number of parents,
        and their ids. Followed by a newline.
        """
        header = self.state_file.readline()
        assert header == '#bazaar dirstate flat format 1\n', \
            'invalid header line: %r' % (header,)
        adler_line = self.state_file.readline()
        assert adler_line.startswith('adler32: '), 'missing adler32 checksum'
        self.adler_expected = int(adler_line[len('adler32: '):-1])
        num_entries_line = self.state_file.readline()
        assert num_entries_line.startswith('num_entries: '), 'missing num_entries line'
        self.num_entries = int(num_entries_line[len('num_entries: '):-1])
    
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
    
    def save(self):
        """Save any pending changes created during this session."""
        self.state_file.seek(0)
        self.state_file.writelines(self.get_lines())
        self.state_file.flush()
        self._clean = True

    def _set_data(self, root_row, tree_data):
        """Set the full dirstate data to root_row and tree_data.

        This is an internal function used to completely replace the objects
        in memory state. It puts the dirstate into state 'full-dirty'.
        """
        # our memory copy is now authoritative.
        self._header_read = True
        self._clean = False
        self._root_row = root_row
        # should save tree_data.


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

