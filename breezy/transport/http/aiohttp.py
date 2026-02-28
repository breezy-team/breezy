# Copyright (C) 2020 Breezy Developers
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

"""aiohttp application for bzr HTTP smart server.
"""

from __future__ import absolute_import

from io import BytesIO

from aiohttp import web

from ...bzr.smart import medium
from ...transport import chroot


async def handle_smart_request(backing_transport, request):
    """Server an smart protocol request using aiohttp.

    :param backing_transport: A backing transport
    :param request: an aiohttp web.Request
    :returns: an aiohttp web.Response
    """
    if request.method != 'POST':
        raise web.HTTPMethodNotAllowed()

    suffix = '/.bzr/smart'
    if not request.path.endswith(suffix):
        raise web.HTTPNotFound()
    relpath = request.path[:-len(suffix)].lstrip('/')

    transport = backing_transport.clone(relpath)

    out_buffer = BytesIO()
    request_data_bytes = await request.read()

    protocol_factory, unused_bytes = medium._get_protocol_factory_for_bytes(
        request_data_bytes)
    smart_protocol_request = protocol_factory(
        transport, out_buffer.write, '.', backing_transport)
    smart_protocol_request.accept_bytes(unused_bytes)
    if smart_protocol_request.next_read_size() != 0:
        # The request appears to be incomplete, or perhaps it's just a
        # newer version we don't understand.  Regardless, all we can do
        # is return an error response in the format of our version of the
        # protocol.
        response_data = b'error\x01incomplete request\n'
    else:
        response_data = out_buffer.getvalue()
    # TODO(jelmer): Use StreamResponse
    return web.Response(
        status=200, body=response_data,
        content_type='application/octet-stream')


if __name__ == '__main__':
    import argparse
    from functools import partial
    from breezy.transport import get_transport
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--directory', '-d', type=str, default='.',
        help='Directory to serve.')
    args = parser.parse_args()
    app = web.Application()
    transport = get_transport(args.directory)
    app.router.add_post(
        '/{path_info:.*}', partial(handle_smart_request, transport))
    web.run_app(app)
