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
"""

from bzrlib.transport.smart import protocol, request


vfs_commands = {}

def register_command(command):
    vfs_commands[command.method] = command


def _deserialise_optional_mode(mode):
    # XXX: FIXME this should be on the protocol object.  Later protocol versions
    # might serialise modes differently.
    if mode == '':
        return None
    else:
        return int(mode)


class HasRequest(request.SmartServerRequest):

    method = 'has'

    def do(self, relpath):
        r = self._backing_transport.has(relpath) and 'yes' or 'no'
        return protocol.SmartServerResponse((r,))
register_command(HasRequest)


class GetRequest(request.SmartServerRequest):

    method = 'get'

    def do(self, relpath):
        backing_bytes = self._backing_transport.get_bytes(relpath)
        return protocol.SmartServerResponse(('ok',), backing_bytes)
register_command(GetRequest)


class AppendRequest(request.SmartServerRequest):

    method = 'append'

    def do(self, relpath, mode):
        self._relpath = relpath
        self._mode = _deserialise_optional_mode(mode)
    
    def do_body(self):
        old_length = self._backing_transport.append_bytes(
            self._relpath, self._body_bytes, self._mode)
        self.response = protocol.SmartServerResponse(('appended', '%d' % old_length))

register_command(AppendRequest)


class DeleteRequest(request.SmartServerRequest):

    method = 'delete'

    def do(self, relpath):
        self._backing_transport.delete(relpath)
register_command(DeleteRequest)


class IterFilesRecursive(request.SmartServerRequest):

    method = 'iter_files_recursive'

    def do(self, relpath):
        transport = self._backing_transport.clone(relpath)
        filenames = transport.iter_files_recursive()
        return protocol.SmartServerResponse(('names',) + tuple(filenames))
register_command(IterFilesRecursive)


class ListDirRequest(request.SmartServerRequest):

    method = 'list_dir'

    def do(self, relpath):
        filenames = self._backing_transport.list_dir(relpath)
        return protocol.SmartServerResponse(('names',) + tuple(filenames))
register_command(ListDirRequest)


class MkdirCommand(request.SmartServerRequest):

    method = 'mkdir'

    def do(self, relpath, mode):
        self._backing_transport.mkdir(relpath,
                                      _deserialise_optional_mode(mode))
        # XXX: shouldn't this return something?
register_command(MkdirCommand)


class MoveCommand(request.SmartServerRequest):

    method = 'move'

    def do(self, rel_from, rel_to):
        self._backing_transport.move(rel_from, rel_to)
        # XXX: shouldn't this return something?
register_command(MoveCommand)


class PutCommand(request.SmartServerRequest):

    method = 'put'

    def do(self, relpath, mode):
        self._relpath = relpath
        self._mode = _deserialise_optional_mode(mode)

    def do_body(self):
        self._backing_transport.put_bytes(self._relpath,
                self._body_bytes, self._mode)
        self.response = protocol.SmartServerResponse(('ok',))
register_command(PutCommand)


class PutNonAtomicCommand(request.SmartServerRequest):

    method = 'put_non_atomic'

    def do(self, relpath, mode, create_parent, dir_mode):
        self._relpath = relpath
        self._dir_mode = _deserialise_optional_mode(dir_mode)
        self._mode = _deserialise_optional_mode(mode)
        # a boolean would be nicer XXX
        self._create_parent = (create_parent == 'T')

    def do_body(self):
        self._backing_transport.put_bytes_non_atomic(self._relpath,
                self._body_bytes,
                mode=self._mode,
                create_parent_dir=self._create_parent,
                dir_mode=self._dir_mode)
        self.response = protocol.SmartServerResponse(('ok',))
register_command(PutNonAtomicCommand)


class ReadvCommand(request.SmartServerRequest):

    method = 'readv'

    def do(self, relpath):
        self._relpath = relpath

    def do_body(self):
        """accept offsets for a readv request."""
        offsets = self._deserialise_offsets(self._body_bytes)
        backing_bytes = ''.join(bytes for offset, bytes in
            self._backing_transport.readv(self._relpath, offsets))
        self.response = protocol.SmartServerResponse(('readv',), backing_bytes)

    def _deserialise_offsets(self, text):
        # XXX: FIXME this should be on the protocol object.
        offsets = []
        for line in text.split('\n'):
            if not line:
                continue
            start, length = line.split(',')
            offsets.append((int(start), int(length)))
        return offsets
register_command(ReadvCommand)


class RenameCommand(request.SmartServerRequest):

    method = 'rename'

    def do(self, rel_from, rel_to):
        self._backing_transport.rename(rel_from, rel_to)
register_command(RenameCommand)


class RmdirCommand(request.SmartServerRequest):

    method = 'rmdir'

    def do(self, relpath):
        self._backing_transport.rmdir(relpath)
register_command(RmdirCommand)


class StatCommand(request.SmartServerRequest):

    method = 'stat'

    def do(self, relpath):
        stat = self._backing_transport.stat(relpath)
        return protocol.SmartServerResponse(
            ('stat', str(stat.st_size), oct(stat.st_mode)))
register_command(StatCommand)

