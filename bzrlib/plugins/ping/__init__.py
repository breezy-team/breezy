# Copyright (C) 2008 Canonical Ltd
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

"""Ping plugin for bzr."""

from bzrlib.commands import Command, register_command
from bzrlib.lazy_import import lazy_import

lazy_import(globals(), """
from bzrlib import errors
from bzrlib.smart.client import _SmartClient
from bzrlib.transport import get_transport
""")


class cmd_ping(Command):
    """Pings a Bazaar smart server.
    
    This command sends a 'hello' request to the given location using the bzr
    smart protocol, and reports the response.
    """

    takes_args = ['location']

    def run(self, location):
        transport = get_transport(location)
        try:
            medium = transport.get_smart_medium()
        except errors.NoSmartMedium, e:
            raise errors.BzrCommandError(str(e))
        client = _SmartClient(medium)
        # Use call_expecting_body (even though we don't expect a body) so that
        # we can see the response headers (if any) via the handler object.
        response, handler = client.call_expecting_body('hello')
        handler.cancel_read_body()
        self.outf.write('Response: %r\n' % (response,))
        if getattr(handler, 'headers', None) is not None:
            self.outf.write('Headers: %r\n' % (handler.headers,))

register_command(cmd_ping)
