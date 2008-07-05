# groupcompress, a bzr plugin providing new compression logic.
# Copyright (C) 2008 Canonical Limited.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
# 

"""Core compression logic for compressing streams of related files."""


from bzrlib import pack
from bzrlib.knit import _DirectPackAccess
from bzrlib.plugins.index2.repofmt import InMemoryBTree
from bzrlib.versionedfile import VersionedFiles


def make_pack_factory(graph, delta, keylength):
    """Create a factory for creating a pack based groupcompress.

    This is only functional enough to run interface tests, it doesn't try to
    provide a full pack environment.
    
    :param graph: Store a graph.
    :param delta: Delta compress contents.
    :param keylength: How long should keys be.
    """
    def factory(transport):
        parents = graph or delta
        ref_length = 0
        if graph:
            ref_length += 1
        if delta:
            ref_length += 1
            max_delta_chain = 200
        else:
            max_delta_chain = 0
        graph_index = InMemoryBTree(reference_lists=ref_length,
            key_elements=keylength)
        stream = transport.open_write_stream('newpack')
        writer = pack.ContainerWriter(stream.write)
        writer.begin()
        index = _GCGraphIndex(graph_index, lambda:True, parents=parents,
            deltas=delta, add_callback=graph_index.add_nodes)
        access = _DirectPackAccess({})
        access.set_writer(writer, graph_index, (transport, 'newpack'))
        result = GroupCompressVersionedFiles(index, access,
            max_delta_chain=max_delta_chain)
        result.stream = stream
        result.writer = writer
        return result
    return factory


def cleanup_pack_group(versioned_files):
    versioned_files.stream.close()
    versioned_files.writer.end()


class GroupCompressVersionedFiles(VersionedFiles):
    """A group-compress based VersionedFiles implementation."""

    def __init__(self, index, access, max_delta_chain=-1):
        """Create a GroupCompressVersionedFiles object.

        :param index: The index object storing access and graph data.
        :param access: The access object storing raw data.
        """


class _GCGraphIndex(object):
    """Mapper from GroupCompressVersionedFiles needs into GraphIndex storage."""

    def __init__(self, graph_index, is_locked, deltas=False, parents=True,
        add_callback=None):
        """Construct a _GCGraphIndex on a graph_index.

        :param graph_index: An implementation of bzrlib.index.GraphIndex.
        :param is_locked: A callback to check whether the object should answer
            queries.
        :param deltas: Allow delta-compressed records.
        :param parents: If True, record knits parents, if not do not record 
            parents.
        :param add_callback: If not None, allow additions to the index and call
            this callback with a list of added GraphIndex nodes:
            [(node, value, node_refs), ...]
        :param is_locked: A callback, returns True if the index is locked and
            thus usable.
        """
        self._add_callback = add_callback
        self._graph_index = graph_index
        self._deltas = deltas
        self._parents = parents
        if deltas and not parents:
            # XXX: TODO: Delta tree and parent graph should be conceptually
            # separate.
            raise KnitCorrupt(self, "Cannot do delta compression without "
                "parent tracking.")
        self.has_graph = parents
        self._is_locked = is_locked

