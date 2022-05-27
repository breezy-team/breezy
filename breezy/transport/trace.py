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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Implementation of Transport that traces transport operations.

This does not change the transport behaviour at all, merely records every call
and then delegates it.
"""

from ..transport import decorator


class TransportTraceDecorator(decorator.TransportDecorator):
    """A tracing decorator for Transports.

    Calls that potentially perform IO are logged to self._activity. The
    _activity attribute is shared as the transport is cloned, but not if a new
    transport is created without cloning.

    Not all operations are logged at this point, if you need an unlogged
    operation please add a test to the tests of this transport, for the logging
    of the operation you want logged.

    See also TransportLogDecorator, that records a machine-readable log in
    memory for eg testing.
    """

    def __init__(self, url, _decorated=None, _from_transport=None):
        """Set the 'base' path where files will be stored.

        _decorated is a private parameter for cloning.
        """
        super(TransportTraceDecorator, self).__init__(url, _decorated)
        if _from_transport is None:
            # newly created
            self._activity = []
        else:
            # cloned
            self._activity = _from_transport._activity

    def append_file(self, relpath, f, mode=None):
        """See Transport.append_file()."""
        return self._decorated.append_file(relpath, f, mode=mode)

    def append_bytes(self, relpath, bytes, mode=None):
        """See Transport.append_bytes()."""
        return self._decorated.append_bytes(relpath, bytes, mode=mode)

    def delete(self, relpath):
        """See Transport.delete()."""
        self._activity.append(('delete', relpath))
        return self._decorated.delete(relpath)

    def delete_tree(self, relpath):
        """See Transport.delete_tree()."""
        return self._decorated.delete_tree(relpath)

    @classmethod
    def _get_url_prefix(self):
        """Tracing transports are identified by 'trace+'"""
        return 'trace+'

    def get(self, relpath):
        """See Transport.get()."""
        self._trace(('get', relpath))
        return self._decorated.get(relpath)

    def get_smart_client(self):
        return self._decorated.get_smart_client()

    def has(self, relpath):
        """See Transport.has()."""
        return self._decorated.has(relpath)

    def is_readonly(self):
        """See Transport.is_readonly."""
        return self._decorated.is_readonly()

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        self._trace(('mkdir', relpath, mode))
        return self._decorated.mkdir(relpath, mode)

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream."""
        return self._decorated.open_write_stream(relpath, mode=mode)

    def put_file(self, relpath, f, mode=None):
        """See Transport.put_file()."""
        return self._decorated.put_file(relpath, f, mode)

    def put_bytes(self, relpath: str, raw_bytes: bytes, mode=None):
        """See Transport.put_bytes()."""
        self._trace(('put_bytes', relpath, len(raw_bytes), mode))
        return self._decorated.put_bytes(relpath, raw_bytes, mode)

    def put_bytes_non_atomic(self, relpath: str, raw_bytes: bytes, mode=None,
                             create_parent_dir=False, dir_mode=None):
        """See Transport.put_bytes_non_atomic."""
        self._trace(('put_bytes_non_atomic', relpath, len(raw_bytes), mode,
                     create_parent_dir, dir_mode))
        return self._decorated.put_bytes_non_atomic(
            relpath, raw_bytes, mode=mode, create_parent_dir=create_parent_dir,
            dir_mode=dir_mode)

    def listable(self):
        """See Transport.listable."""
        return self._decorated.listable()

    def iter_files_recursive(self):
        """See Transport.iter_files_recursive()."""
        return self._decorated.iter_files_recursive()

    def list_dir(self, relpath):
        """See Transport.list_dir()."""
        return self._decorated.list_dir(relpath)

    def readv(self, relpath, offsets, adjust_for_latency=False,
              upper_limit=None):
        # we override at the readv() level rather than _readv() so that any
        # latency adjustments will be done by the underlying transport
        self._trace(('readv', relpath, offsets, adjust_for_latency,
                     upper_limit))
        return self._decorated.readv(relpath, offsets, adjust_for_latency,
                                     upper_limit)

    def recommended_page_size(self):
        """See Transport.recommended_page_size()."""
        return self._decorated.recommended_page_size()

    def rename(self, rel_from, rel_to):
        self._activity.append(('rename', rel_from, rel_to))
        return self._decorated.rename(rel_from, rel_to)

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        self._trace(('rmdir', relpath))
        return self._decorated.rmdir(relpath)

    def stat(self, relpath):
        """See Transport.stat()."""
        return self._decorated.stat(relpath)

    def lock_read(self, relpath):
        """See Transport.lock_read."""
        return self._decorated.lock_read(relpath)

    def lock_write(self, relpath):
        """See Transport.lock_write."""
        return self._decorated.lock_write(relpath)

    def _trace(self, operation_tuple):
        """Record that a transport operation occured.

        :param operation: Tuple of transport call name and arguments.
        """
        self._activity.append(operation_tuple)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from breezy.tests import test_server
    return [(TransportTraceDecorator, test_server.TraceServer)]
