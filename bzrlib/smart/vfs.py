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

"""VFS operations for the smart server.

This module defines the smart server methods that are low-level file operations
-- i.e. methods that operate directly on files and directories, rather than
higher-level concepts like branches and revisions.

These methods, plus 'hello' and 'get_bundle', are version 1 of the smart server
protocol, as implemented in bzr 0.11 and later.
"""

import os

from bzrlib import errors
from bzrlib.smart import request


def _deserialise_optional_mode(mode):
    # XXX: FIXME this should be on the protocol object.  Later protocol versions
    # might serialise modes differently.
    if mode == '':
        return None
    else:
        return int(mode)


def vfs_enabled():
    """Is the VFS enabled ?

    the VFS is disabled when the NO_SMART_VFS environment variable is set.

    :return: True if it is enabled.
    """
    return not 'NO_SMART_VFS' in os.environ


class VfsRequest(request.SmartServerRequest):
    """Base class for VFS requests.
    
    VFS requests are disabled if vfs_enabled() returns False.
    """

    def _check_enabled(self):
        if not vfs_enabled():
            raise errors.DisabledMethod(self.__class__.__name__)


class HasRequest(VfsRequest):

    def do(self, relpath):
        r = self._backing_transport.has(relpath) and 'yes' or 'no'
        return request.SmartServerResponse((r,))


class GetRequest(VfsRequest):

    def do(self, relpath):
        backing_bytes = self._backing_transport.get_bytes(relpath)
        return request.SmartServerResponse(('ok',), backing_bytes)


class AppendRequest(VfsRequest):

    def do(self, relpath, mode):
        self._relpath = relpath
        self._mode = _deserialise_optional_mode(mode)
    
    def do_body(self, body_bytes):
        old_length = self._backing_transport.append_bytes(
            self._relpath, body_bytes, self._mode)
        return request.SmartServerResponse(('appended', '%d' % old_length))


class DeleteRequest(VfsRequest):

    def do(self, relpath):
        self._backing_transport.delete(relpath)
        return request.SmartServerResponse(('ok', ))


class IterFilesRecursiveRequest(VfsRequest):

    def do(self, relpath):
        transport = self._backing_transport.clone(relpath)
        filenames = transport.iter_files_recursive()
        return request.SmartServerResponse(('names',) + tuple(filenames))


class ListDirRequest(VfsRequest):

    def do(self, relpath):
        filenames = self._backing_transport.list_dir(relpath)
        return request.SmartServerResponse(('names',) + tuple(filenames))


class MkdirRequest(VfsRequest):

    def do(self, relpath, mode):
        self._backing_transport.mkdir(relpath,
                                      _deserialise_optional_mode(mode))
        return request.SmartServerResponse(('ok',))


class MoveRequest(VfsRequest):

    def do(self, rel_from, rel_to):
        self._backing_transport.move(rel_from, rel_to)
        return request.SmartServerResponse(('ok',))


class PutRequest(VfsRequest):

    def do(self, relpath, mode):
        self._relpath = relpath
        self._mode = _deserialise_optional_mode(mode)

    def do_body(self, body_bytes):
        self._backing_transport.put_bytes(self._relpath, body_bytes, self._mode)
        return request.SmartServerResponse(('ok',))


class PutNonAtomicRequest(VfsRequest):

    def do(self, relpath, mode, create_parent, dir_mode):
        self._relpath = relpath
        self._dir_mode = _deserialise_optional_mode(dir_mode)
        self._mode = _deserialise_optional_mode(mode)
        # a boolean would be nicer XXX
        self._create_parent = (create_parent == 'T')

    def do_body(self, body_bytes):
        self._backing_transport.put_bytes_non_atomic(self._relpath,
                body_bytes,
                mode=self._mode,
                create_parent_dir=self._create_parent,
                dir_mode=self._dir_mode)
        return request.SmartServerResponse(('ok',))


class ReadvRequest(VfsRequest):

    def do(self, relpath):
        self._relpath = relpath

    def do_body(self, body_bytes):
        """accept offsets for a readv request."""
        offsets = self._deserialise_offsets(body_bytes)
        backing_bytes = ''.join(bytes for offset, bytes in
            self._backing_transport.readv(self._relpath, offsets))
        return request.SmartServerResponse(('readv',), backing_bytes)

    def _deserialise_offsets(self, text):
        # XXX: FIXME this should be on the protocol object.
        offsets = []
        for line in text.split('\n'):
            if not line:
                continue
            start, length = line.split(',')
            offsets.append((int(start), int(length)))
        return offsets


class RenameRequest(VfsRequest):

    def do(self, rel_from, rel_to):
        self._backing_transport.rename(rel_from, rel_to)
        return request.SmartServerResponse(('ok', ))


class RmdirRequest(VfsRequest):

    def do(self, relpath):
        self._backing_transport.rmdir(relpath)
        return request.SmartServerResponse(('ok', ))


class StatRequest(VfsRequest):

    def do(self, relpath):
        stat = self._backing_transport.stat(relpath)
        return request.SmartServerResponse(
            ('stat', str(stat.st_size), oct(stat.st_mode)))

