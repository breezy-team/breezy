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
import time
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


    @staticmethod
    def from_tree(tree, base_path):
        """Create a dirstate from a bzr Tree and a local disk path.

        :param tree: The tree which should provide parent information and
            inventory ids.
        :param base_path: The local path to access the local fs data for this tree.
            This is not accessed via the tree object because we want to be able
            to seed DirStates from RevisionTrees during checkout. Possibly
            a better model is to start with an empty dirstate and populate it
            during the checkout operation, but that will require looking at the
            behaviour of set_inventory etc. which is not in scope yet - and is
            potentially very expensive as it requires an entire scan, or an
            inventory diff.
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

        # FIXME: is this utf8 safe?
        lines.append('\0'.join([str(num_parents)] + parent_ids))

        to_minikind = DirState._kind_to_minikind

        st = os.lstat(base_path)
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

        test_sha = sha.new('').hexdigest()

        tstart = time.time()
        for dirinfo, block in tree.walkdirs():

            to_remove = []
            for relpath, name, kind, st, fileid, versionedkind in block:
                if fileid is None:
                    # unversioned file, skip
                    continue
                s = None
                symlink_target = None
                dirname, basename = os.path.split(relpath.encode('utf8'))
                if kind == 'file':
                    #s = sha_file(open(abspath, 'rb'))
                    s = test_sha
                elif kind == 'directory':
                    if name in ('.bzr', '.hg', 'CVS', '.svn', '_svn'):
                        # Skip this, and all children
                        to_remove.append((relpath, name, kind, st, abspath))
                        continue
                    s = ''
                elif kind == 'symlink':
                    s = os.readlink(abspath)

                parent_info = []
                if num_parents >= 1:
                    parent_info.append(
                        '\0'.join((
                            parent_ids[0]
                            , to_minikind[kind]
                            , dirname, basename
                            , str(st.st_size)
                            , 'n' # Not executable
                            , s
                            )))
                if num_parents >= 2:
                    parent_info.append(
                        '\0'.join((
                            parent_ids[0]
                            , to_minikind[kind]
                            , dirname, basename
                            , str(st.st_size)
                            , 'n' # Not executable
                            , s
                            )))
                for count in xrange(2,num_parents):
                    parent_info.append(null_parent_info)
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

        output_lines = ['#bzr dirstate flat format 1\n']

        lines.append('') # a final newline
        inventory_text = '\0\n\0'.join(lines)
        output_lines.append('adler32: %s\n' % (zlib.adler32(inventory_text),))
        # -2, 1 for num parents, 1 for final newline
        num_entries = len(lines)-2
        output_lines.append('num_entries: %s\n' % (num_entries,))
        output_lines.append(inventory_text)

        result.lines = output_lines
        return result

    def get_lines(self):
        """Serialise the entire dirstate to a sequence of lines."""
        return self.lines
        return [
            '#bzr dirstate flat format 1\n',
            'adler32: -2\n',
            'num_entries: 1\n',
            '0\x00\n',
            '\x00\x00\x00d\x00TREE_ROOT\x004096\x00AAAQAETIF65EyBeuAAADAQAQQxsAAEHt\x00\x00\n',
            '\x00',
            ]

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

