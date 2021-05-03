# Copyright (C) 2008-2012 Canonical Ltd
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

"""Ping plugin for brz."""

from ...commands import Command
from ...lazy_import import lazy_import

lazy_import(globals(), """
from breezy.bzr.smart.client import _SmartClient
from breezy.transport import get_transport
""")

from breezy import errors


class cmd_ping(Command):
    """Pings a Bazaar smart server.

    This command sends a 'hello' request to the given location using the brz
    smart protocol, and reports the response.
    """

    takes_args = ['location']

    def run(self, location):
        transport = get_transport(location)
        try:
            medium = transport.get_smart_medium()
        except errors.NoSmartMedium as e:
            raise errors.CommandError(str(e))
        client = _SmartClient(medium)
        # Use call_expecting_body (even though we don't expect a body) so that
        # we can see the response headers (if any) via the handler object.
        response, handler = client.call_expecting_body(b'hello')
        handler.cancel_read_body()
        self.outf.write('Response: %r\n' % (response,))
        if getattr(handler, 'headers', None) is not None:
            headers = {
                k.decode('utf-8'): v.decode('utf-8')
                for (k, v) in handler.headers.items()}
            self.outf.write('Headers: %r\n' % (headers,))
