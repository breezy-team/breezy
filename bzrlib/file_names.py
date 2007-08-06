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

"""A collection of file names which is persisted on a transport."""

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
        errors,
        )
""")


class FileNames(object):
    """A collection of file names.

    The file names are persisted to a file on a transport, and cand be
    added, removed and initialised.

    The set of names are stored in a flat file, one name per line.
    New names are allocated sequentially.
    Initialisation creates an empty file.

    This is intended to support management of modest numbers of files in 
    write-locked environments which may be read from unlistable transports.
    
    The save method must be called to cause the state to be saved to the
    transport.

    The load method is used to obtain a previously saved set.

    There is a cap in the _cap method which will error if more names are
    added than the names collection can sensibly manage. Currently this
    cap is 10000.
    """

    def __init__(self, transport, index_name):
        """Create a collection on transport called index_name."""
        self._transport = transport
        self._index_name = index_name
        self._names = None
        self._cap = 10000

    def allocate(self, name=None):
        """Allocate name in the names collection.

        :param name: The name to allocate.
        :raises: bzrlib.errors.DuplicateKey if the name is already allocated.
        """
        if name is not None:
            if len(self._names) >= self._cap:
                raise errors.BzrError('too many files')
            if name in self._names:
                raise errors.DuplicateKey(name)
            self._names.add(name)
            return name

    def initialise(self):
        """Initialise the collection."""
        self._names = set()

    def load(self):
        """Load the names from the transport."""
        self._names = set(self._transport.get_bytes(
            self._index_name).split('\n'))
        self._names.discard('')

    def names(self):
        """What are the names in this collection?"""
        return frozenset(self._names)

    def remove(self, name):
        """Remove name from the collection."""
        self._names.remove(name)

    def save(self):
        """Save the set of names."""
        self._transport.put_bytes(self._index_name, '\n'.join(self._names))

