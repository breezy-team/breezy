# Copyright (C) 2006 Canonical Ltd
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

"""Implementation of Transport that prevents access to locations above a set
root.
"""
from urlparse import urlparse

from bzrlib import errors, urlutils
from bzrlib.transport.decorator import TransportDecorator, DecoratorServer


class ChrootTransportDecorator(TransportDecorator):
    """A decorator that can convert any transport to be chrooted.

    This is requested via the 'chroot+' prefix to get_transport().

    :ivar chroot_url: the root of this chroot
    :ivar chroot_relative: this transport's location relative to the chroot
        root.  e.g. A chroot_relative of '/' means this location is the same as
        chroot_url.
    """

    def __init__(self, url, _decorated=None, chroot=None):
        super(ChrootTransportDecorator, self).__init__(url,
                _decorated=_decorated)
        if chroot is None:
            self.chroot_url = self._decorated.base
        else:
            self.chroot_url = chroot
        self.chroot_relative = '/' + self._decorated.base[len(self.chroot_url):]

    @classmethod
    def _get_url_prefix(self):
        """Chroot transport decorators are invoked via 'chroot+'"""
        return 'chroot+'

    def _ensure_relpath_is_child(self, relpath):
        abspath = self.abspath(relpath)
        chroot_base = self._get_url_prefix() + self.chroot_url
        real_relpath = urlutils.relative_url(chroot_base, abspath)
        if real_relpath == '..' or real_relpath.startswith('../'):
            raise errors.PathNotChild(relpath, self.chroot_url)

    # decorated methods
    def abspath(self, relpath):
        try:
            url = urlutils.join('fake:///', relpath)
        except errors.InvalidURLJoin:
            raise errors.PathNotChild(relpath, self.chroot_url)
        normalised_abspath = url[len('fake:///'):]
        return self._get_url_prefix() + self.chroot_url + normalised_abspath[1:]

    def append_file(self, relpath, f, mode=None):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.append_file(self, relpath, f, mode=mode)

    def append_bytes(self, relpath, bytes, mode=None):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.append_bytes(self, relpath, bytes, mode=mode)

    def clone(self, offset=None):
        if offset is None: return self
        # the new URL we want to clone to is
        # self.chroot_url + an adjusted self.chroot_relative, with the leading
        # / removed.
        new_relpath = urlutils.joinpath(self.chroot_relative, offset)
        assert new_relpath.startswith('/')
        new_url = self.chroot_url + new_relpath[1:]
        # Clone the decorated transport according to this new path.
        assert new_url.startswith(self.chroot_url), (
            'new_url (%r) does not start with %r'
            % (new_url, self._decorated.base))
        path = urlutils.relative_url(self._decorated.base, new_url)
        decorated_clone = self._decorated.clone(path)
        return ChrootTransportDecorator(self._get_url_prefix() + new_url,
            decorated_clone, self.chroot_url)

    def delete(self, relpath):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.delete(self, relpath)

    def delete_tree(self, relpath):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.delete_tree(self, relpath)

    def get(self, relpath):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.get(self, relpath)

    def get_bytes(self, relpath):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.get_bytes(self, relpath)

    def has(self, relpath):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.has(self, relpath)

    def list_dir(self, relpath):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.list_dir(self, relpath)

    def lock_read(self, relpath):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.lock_read(self, relpath)

    def lock_write(self, relpath):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.lock_write(self, relpath)

    def mkdir(self, relpath, mode=None):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.mkdir(self, relpath, mode=mode)

    def put_bytes(self, relpath, bytes, mode=None):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.put_bytes(self, relpath, bytes, mode=mode)

    def put_file(self, relpath, f, mode=None):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.put_file(self, relpath, f, mode=mode)

    def rename(self, rel_from, rel_to):
        self._ensure_relpath_is_child(rel_from)
        self._ensure_relpath_is_child(rel_to)
        return TransportDecorator.rename(self, rel_from, rel_to)

    def rmdir(self, relpath):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.rmdir(self, relpath)

    def stat(self, relpath):
        self._ensure_relpath_is_child(relpath)
        return TransportDecorator.stat(self, relpath)


class ChrootServer(DecoratorServer):
    """Server for the ReadonlyTransportDecorator for testing with."""

    def get_decorator_class(self):
        return ChrootTransportDecorator


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(ChrootTransportDecorator, ChrootServer),
            ]
