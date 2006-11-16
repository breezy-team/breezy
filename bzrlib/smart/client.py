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

from bzrlib.smart import protocol


class SmartClient(object):

    def __init__(self, medium):
        self._medium = medium

    def call(self, method, *args):
        """Call a method on the remote server."""
        request = self._medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call(method, *args)
        return smart_protocol.read_response_tuple()

    def call_with_body_bytes(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        request = self._medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call_with_body_bytes((method, ) + args, body)
        return smart_protocol.read_response_tuple()

