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

import tempfile

from bzrlib import bzrdir, revision
from bzrlib.bundle.serializer import write_bundle
from bzrlib.transport.smart import protocol


class SmartServerRequest(object):
    """Base class for request handlers.

    (Command pattern.)
    """

    def __init__(self, backing_transport):
        self._backing_transport = backing_transport

    def do(self):
        raise NotImplementedError(self.do)

    def do_body(self, body_bytes):
        raise NotImplementedError(self.do_body)


class HelloRequest(SmartServerRequest):
    """Answer a version request with my version."""

    method = 'hello'

    def do(self):
        return protocol.SmartServerResponse(('ok', '1'))


class GetBundleRequest(SmartServerRequest):

    method = 'get_bundle'

    def do(self, path, revision_id):
        # open transport relative to our base
        t = self._backing_transport.clone(path)
        control, extra_path = bzrdir.BzrDir.open_containing_from_transport(t)
        repo = control.open_repository()
        tmpf = tempfile.TemporaryFile()
        base_revision = revision.NULL_REVISION
        write_bundle(repo, revision_id, base_revision, tmpf)
        tmpf.seek(0)
        return protocol.SmartServerResponse((), tmpf.read())


# This is extended by bzrlib/transport/smart/vfs.py
version_one_commands = {
    HelloRequest.method: HelloRequest,
    GetBundleRequest.method: GetBundleRequest,
}


