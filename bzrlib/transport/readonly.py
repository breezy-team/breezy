# Copyright (C) 2006 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Implementation of Transport that adapts another transport to be readonly."""

from bzrlib.errors import TransportNotPossible
from bzrlib.transport.decorator import TransportDecorator, DecoratorServer


class ReadonlyTransportDecorator(TransportDecorator):
    """A decorator that can convert any transport to be readonly.

    This is requested via the 'readonly+' prefix to get_transport().
    """

    def append(self, relpath, f):
        """See Transport.append()."""
        raise TransportNotPossible('readonly transport')
    
    @classmethod
    def _get_url_prefix(self):
        """Readonly transport decorators are invoked via 'readonly+'"""
        return 'readonly+'

    def delete(self, relpath):
        """See Transport.delete()."""
        raise TransportNotPossible('readonly transport')

    def delete_tree(self, relpath):
        """See Transport.delete_tree()."""
        raise TransportNotPossible('readonly transport')

    def put(self, relpath, f, mode=None):
        """See Transport.put()."""
        raise TransportNotPossible('readonly transport')

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        raise TransportNotPossible('readonly transport')

    def is_readonly(self):
        """See Transport.is_readonly."""
        return True

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        raise TransportNotPossible('readonly transport')

    def lock_write(self, relpath):
        """See Transport.lock_write."""
        raise TransportNotPossible('readonly transport')


class ReadonlyServer(DecoratorServer):
    """Server for the ReadonlyTransportDecorator for testing with."""

    def get_decorator_class(self):
        return ReadonlyTransportDecorator


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(ReadonlyTransportDecorator, ReadonlyServer),
            ]
