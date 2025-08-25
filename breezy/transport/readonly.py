# Copyright (C) 2006, 2007, 2009, 2010, 2011, 2016 Canonical Ltd
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

"""Implementation of Transport that adapts another transport to be readonly."""

from ..errors import NoSmartMedium, TransportNotPossible
from ..transport import decorator


class ReadonlyTransportDecorator(decorator.TransportDecorator):
    """A decorator that can convert any transport to be readonly.

    This is requested via the 'readonly+' prefix to get_transport().
    """

    def append_file(self, relpath, f, mode=None):
        """See Transport.append_file()."""
        raise TransportNotPossible("readonly transport")

    def append_bytes(self, relpath, bytes, mode=None):
        """See Transport.append_bytes()."""
        raise TransportNotPossible("readonly transport")

    @classmethod
    def _get_url_prefix(self):
        """Readonly transport decorators are invoked via 'readonly+'."""
        return "readonly+"

    def rename(self, rel_from, rel_to):
        """See Transport.rename."""
        raise TransportNotPossible("readonly transport")

    def delete(self, relpath):
        """See Transport.delete()."""
        raise TransportNotPossible("readonly transport")

    def delete_tree(self, relpath):
        """See Transport.delete_tree()."""
        raise TransportNotPossible("readonly transport")

    def put_file(self, relpath, f, mode=None):
        """See Transport.put_file()."""
        raise TransportNotPossible("readonly transport")

    def put_bytes(self, relpath: str, raw_bytes: bytes, mode=None):
        """See Transport.put_bytes()."""
        raise TransportNotPossible("readonly transport")

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        raise TransportNotPossible("readonly transport")

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream()."""
        raise TransportNotPossible("readonly transport")

    def is_readonly(self):
        """See Transport.is_readonly."""
        return True

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        raise TransportNotPossible("readonly transport")

    def lock_write(self, relpath):
        """See Transport.lock_write."""
        raise TransportNotPossible("readonly transport")

    def get_smart_client(self):
        """Get a smart protocol client.

        Raises:
            NoSmartMedium: Always raised as readonly transport doesn't support smart operations.
        """
        raise NoSmartMedium(self)

    def get_smart_medium(self):
        """Get a smart protocol medium.

        Raises:
            NoSmartMedium: Always raised as readonly transport doesn't support smart operations.
        """
        raise NoSmartMedium(self)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from ..tests import test_server

    return [(ReadonlyTransportDecorator, test_server.ReadonlyServer)]
