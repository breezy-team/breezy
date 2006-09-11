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

"""DirState objects record the state of a directory and its bzr metadata."""


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
        to_yesno = {True:'y', False: 'n'}

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
                        '\0'.join((
                            parent_entry.revision,
                            to_minikind[parent_entry.kind],
                            # FIXME: set these from the parent
                            dirname, basename,
                            str(parent_entry.text_size),
                            to_yesno[parent_entry.executable],
                            parent_entry.text_sha1,
                            )))
                lines.append('\0'.join([
                    dirname, basename
                    , to_minikind[kind]
                    , fileid.encode('utf8')
                    , str(st.st_size)
                    , pack_stat(st)
                    , s
                    ] + parent_info
                    ))

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
        """Create a new dirstate on path."""
        result = DirState()
        # tell the dirstate that its memory copy is accurate - and the default
        # memmory structure is a clean dirstate.
        result._header_read = True
        result.state_file = open(path, 'wb+')
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
        output_lines = ['#bzr dirstate flat format 1\n']
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
        assert header == '#bzr dirstate flat format 1\n', \
            'invalid header line: %r' % (header,)
        adler_line = self.state_file.readline()
        assert adler_line.startswith('adler32: '), 'missing adler32 checksum'
        self.adler_expected = int(adler_line[len('adler32: '):-1])
        num_entries_line = self.state_file.readline()
        assert num_entries_line.startswith('num_entries: '), 'missing num_entries line'
        self.num_entries = int(num_entries_line[len('num_entries: '):-1])
    
    def save(self):
        """Save any pending changes created during this session."""
        self.state_file.seek(0)
        self.state_file.writelines(self.get_lines())
        self.state_file.flush()
        self._clean = True

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

