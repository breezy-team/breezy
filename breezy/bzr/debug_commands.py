# Copyright (C) 2005-2012 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Debug commands for the bzr formats."""

from io import BytesIO

from .. import errors, osutils, transport
from ..commands import Command, display_command
from ..option import Option
from ..workingtree import WorkingTree
from . import btree_index


def as_tuples(obj):
    """Ensure that the object and any referenced objects are plain tuples.

    :param obj: a list, tuple or StaticTuple
    :return: a plain tuple instance, with all children also being tuples.
    """
    result = []
    for item in obj:
        if isinstance(item, (tuple, list)):
            item = as_tuples(item)
        result.append(item)
    return tuple(result)


class cmd_dump_btree(Command):
    """Command to dump btree index file contents."""

    __doc__ = """Dump the contents of a btree index file to stdout.

    PATH is a btree index file, it can be any URL. This includes things like
    .bzr/repository/pack-names, or .bzr/repository/indices/a34b3a...ca4a4.iix

    By default, the tuples stored in the index file will be displayed. With
    --raw, we will uncompress the pages, but otherwise display the raw bytes
    stored in the index.
    """

    # TODO: Do we want to dump the internal nodes as well?
    # TODO: It would be nice to be able to dump the un-parsed information,
    #       rather than only going through iter_all_entries. However, this is
    #       good enough for a start
    hidden = True
    encoding_type = "exact"
    takes_args = ["path"]
    takes_options = [
        Option(
            "raw",
            help="Write the uncompressed bytes out, rather than the parsed tuples.",
        ),
    ]

    def run(self, path, raw=False):
        """Execute the btree dump command."""
        dirname, basename = osutils.split(path)
        t = transport.get_transport(dirname)
        if raw:
            self._dump_raw_bytes(t, basename)
        else:
            self._dump_entries(t, basename)

    def _get_index_and_bytes(self, trans, basename):
        """Create a BTreeGraphIndex and raw bytes."""
        bt = btree_index.BTreeGraphIndex(trans, basename, None)
        bytes = trans.get_bytes(basename)
        bt._file = BytesIO(bytes)
        bt._size = len(bytes)
        return bt, bytes

    def _dump_raw_bytes(self, trans, basename):
        import zlib

        # We need to parse at least the root node.
        # This is because the first page of every row starts with an
        # uncompressed header.
        bt, bytes = self._get_index_and_bytes(trans, basename)
        for page_idx, page_start in enumerate(
            range(0, len(bytes), btree_index._PAGE_SIZE)
        ):
            page_end = min(page_start + btree_index._PAGE_SIZE, len(bytes))
            page_bytes = bytes[page_start:page_end]
            if page_idx == 0:
                self.outf.write("Root node:\n")
                header_end, data = bt._parse_header_from_bytes(page_bytes)
                self.outf.write(page_bytes[:header_end])
                page_bytes = data
            self.outf.write("\nPage %d\n" % (page_idx,))
            if len(page_bytes) == 0:
                self.outf.write("(empty)\n")
            else:
                decomp_bytes = zlib.decompress(page_bytes)
                self.outf.write(decomp_bytes)
                self.outf.write("\n")

    def _dump_entries(self, trans, basename):
        try:
            st = trans.stat(basename)
        except errors.TransportNotPossible:
            # We can't stat, so we'll fake it because we have to do the 'get()'
            # anyway.
            bt, _ = self._get_index_and_bytes(trans, basename)
        else:
            bt = btree_index.BTreeGraphIndex(trans, basename, st.st_size)
        for node in bt.iter_all_entries():
            # Node is made up of:
            # (index, key, value, [references])
            try:
                refs = node[3]
            except IndexError:
                refs_as_tuples = None
            else:
                refs_as_tuples = as_tuples(refs)
            if refs_as_tuples is not None:
                refs_as_tuples = tuple(
                    tuple(tuple(r.decode("utf-8") for r in t1) for t1 in t2)
                    for t2 in refs_as_tuples
                )
            as_tuple = (
                tuple([r.decode("utf-8") for r in node[1]]),
                node[2].decode("utf-8"),
                refs_as_tuples,
            )
            self.outf.write(f"{as_tuple}\n")


class cmd_file_id(Command):
    """Command to print file_id of a file or directory."""

    __doc__ = """Print file_id of a particular file or directory.

    The file_id is assigned when the file is first added and remains the
    same through all revisions where the file exists, even when it is
    moved or renamed.
    """

    hidden = True
    _see_also = ["inventory", "ls"]
    takes_args = ["filename"]

    @display_command
    def run(self, filename):
        """Execute the file_id command."""
        tree, relpath = WorkingTree.open_containing(filename)
        file_id = tree.path2id(relpath)
        if file_id is None:
            raise errors.NotVersionedError(filename)
        else:
            self.outf.write(file_id.decode("utf-8") + "\n")


class cmd_file_path(Command):
    """Command to print path of file_ids to a file or directory."""

    __doc__ = """Print path of file_ids to a file or directory.

    This prints one line for each directory down to the target,
    starting at the branch root.
    """

    hidden = True
    takes_args = ["filename"]

    @display_command
    def run(self, filename):
        """Execute the file_path command."""
        tree, relpath = WorkingTree.open_containing(filename)
        fid = tree.path2id(relpath)
        if fid is None:
            raise errors.NotVersionedError(filename)
        segments = osutils.splitpath(relpath)
        for pos in range(1, len(segments) + 1):
            path = osutils.joinpath(segments[:pos])
            self.outf.write(f"{tree.path2id(path)}\n")
