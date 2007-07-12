# Copyright (C) 2007 Canonical Ltd
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

"""Indexing facilities."""

from cStringIO import StringIO

from bzrlib import errors

_OPTION_NODE_REFS = "node_ref_lists="
_SIGNATURE = "Bazaar Graph Index 1\n"


class GraphIndexBuilder(object):
    """A builder that can build a GraphIndex."""

    def __init__(self, reference_lists=0):
        """Create a GraphIndex builder.

        :param reference_lists: The number of node references lists for each
            entry.
        """
        self.reference_lists = reference_lists

    def finish(self):
        lines = [_SIGNATURE]
        lines.append(_OPTION_NODE_REFS + str(self.reference_lists) + '\n')
        lines.append('\n')
        return StringIO(''.join(lines))


class GraphIndex(object):
    """An index for data with embedded graphs.
 
    The index maps keys to a list of key reference lists, and a value.
    Each node has the same number of key reference lists. Each key reference
    list can be empty or an arbitrary length. The value is an opaque NULL
    terminated string.
    """

    def __init__(self, transport, name):
        """Open an index called name on transport.

        :param transport: A bzrlib.transport.Transport.
        :param name: A path to provide to transport API calls.
        """
        self._transport = transport
        self._name = name

    def iter_all_entries(self):
        """Iterate over all keys within the index.

        :return: An iterable of (key, reference_lists, value). There is no
            defined order for the result iteration - it will be in the most
            efficient order for the index.
        """
        return []

    def iter_entries(self, keys):
        """Iterate over keys within the index.

        :param keys: An iterable providing the keys to be retrieved.
        :return: An iterable of (key, reference_lists, value). There is no
            defined order for the result iteration - it will be in the most
            efficient order for the index.
        """
        if not keys:
            return
        if False:
            yield None
        raise errors.MissingKey(self, keys[0])

    def _signature(self):
        """The file signature for this index type."""
        return _SIGNATURE

    def validate(self):
        """Validate that everything in the index can be accessed."""
        stream = self._transport.get(self._name)
        signature = stream.read(len(self._signature()))
        if not signature == self._signature():
            raise errors.BadIndexFormatSignature(self._name, GraphIndex)
        options_line = stream.readline()
        if not options_line.startswith(_OPTION_NODE_REFS):
            raise errors.BadIndexOptions(self)
        try:
            node_ref_lists = int(options_line[len(_OPTION_NODE_REFS):-1])
        except ValueError:
            raise errors.BadIndexOptions(self)
