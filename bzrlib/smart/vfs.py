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

from bzrlib.smart import request


def _deserialise_optional_mode(mode):
    # XXX: FIXME this should be on the protocol object.  Later protocol versions
    # might serialise modes differently.
    if mode == '':
        return None
    else:
        return int(mode)


class HasRequest(request.SmartServerRequest):

    def do(self, relpath):
        r = self._backing_transport.has(relpath) and 'yes' or 'no'
        return request.SmartServerResponse((r,))


class GetRequest(request.SmartServerRequest):

    def do(self, relpath):
        backing_bytes = self._backing_transport.get_bytes(relpath)
        return request.SmartServerResponse(('ok',), backing_bytes)


class AppendRequest(request.SmartServerRequest):

    def do(self, relpath, mode):
        self._relpath = relpath
        self._mode = _deserialise_optional_mode(mode)
    
    def do_body(self, body_bytes):
        old_length = self._backing_transport.append_bytes(
            self._relpath, body_bytes, self._mode)
        return request.SmartServerResponse(('appended', '%d' % old_length))


class DeleteRequest(request.SmartServerRequest):

    def do(self, relpath):
        self._backing_transport.delete(relpath)
        return request.SmartServerResponse(('ok', ))


class IterFilesRecursive(request.SmartServerRequest):

    def do(self, relpath):
        transport = self._backing_transport.clone(relpath)
        filenames = transport.iter_files_recursive()
        return request.SmartServerResponse(('names',) + tuple(filenames))


class ListDirRequest(request.SmartServerRequest):

    def do(self, relpath):
        filenames = self._backing_transport.list_dir(relpath)
        return request.SmartServerResponse(('names',) + tuple(filenames))


class MkdirCommand(request.SmartServerRequest):

    def do(self, relpath, mode):
        self._backing_transport.mkdir(relpath,
                                      _deserialise_optional_mode(mode))
        return request.SmartServerResponse(('ok',))


class MoveCommand(request.SmartServerRequest):

    def do(self, rel_from, rel_to):
        self._backing_transport.move(rel_from, rel_to)
        return request.SmartServerResponse(('ok',))


class PutCommand(request.SmartServerRequest):

    def do(self, relpath, mode):
        self._relpath = relpath
        self._mode = _deserialise_optional_mode(mode)

    def do_body(self, body_bytes):
        self._backing_transport.put_bytes(self._relpath, body_bytes, self._mode)
        return request.SmartServerResponse(('ok',))


class PutNonAtomicCommand(request.SmartServerRequest):

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


class ReadvCommand(request.SmartServerRequest):

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


class RenameCommand(request.SmartServerRequest):

    def do(self, rel_from, rel_to):
        self._backing_transport.rename(rel_from, rel_to)
        return request.SmartServerResponse(('ok', ))


class RmdirCommand(request.SmartServerRequest):

    def do(self, relpath):
        self._backing_transport.rmdir(relpath)
        return request.SmartServerResponse(('ok', ))


class StatCommand(request.SmartServerRequest):

    def do(self, relpath):
        stat = self._backing_transport.stat(relpath)
        return request.SmartServerResponse(
            ('stat', str(stat.st_size), oct(stat.st_mode)))

