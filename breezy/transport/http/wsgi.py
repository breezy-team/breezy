# Copyright (C) 2006-2010 Canonical Ltd
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

"""WSGI application for bzr HTTP smart server.

For more information about WSGI, see PEP 333:
    http://www.python.org/dev/peps/pep-0333/
"""

from io import BytesIO

from ...bzr.smart import medium
from ...transport import chroot, get_transport
from ...urlutils import local_path_to_url


def make_app(root, prefix, path_var='REQUEST_URI', readonly=True,
             load_plugins=True, enable_logging=True):
    """Convenience function to construct a WSGI bzr smart server.

    :param root: a local path that requests will be relative to.
    :param prefix: See RelpathSetter.
    :param path_var: See RelpathSetter.
    """
    local_url = local_path_to_url(root)
    if readonly:
        base_transport = get_transport('readonly+' + local_url)
    else:
        base_transport = get_transport(local_url)
    if load_plugins:
        from ...plugin import load_plugins
        load_plugins()
    if enable_logging:
        import breezy.trace
        breezy.trace.enable_default_logging()
    app = SmartWSGIApp(base_transport, prefix)
    app = RelpathSetter(app, '', path_var)
    return app


class RelpathSetter(object):
    """WSGI middleware to set 'breezy.relpath' in the environ.

    Different servers can invoke a SmartWSGIApp in different ways.  This
    middleware allows an adminstrator to configure how to the SmartWSGIApp will
    determine what path it should be serving for a given request for many common
    situations.

    For example, a request for "/some/prefix/repo/branch/.bzr/smart" received by
    a typical Apache and mod_fastcgi configuration will set `REQUEST_URI` to
    "/some/prefix/repo/branch/.bzr/smart".  A RelpathSetter with
    prefix="/some/prefix/" and path_var="REQUEST_URI" will set that request's
    'breezy.relpath' variable to "repo/branch".
    """

    def __init__(self, app, prefix='', path_var='REQUEST_URI'):
        """Constructor.

        :param app: WSGI app to wrap, e.g. a SmartWSGIApp instance.
        :param path_var: the variable in the WSGI environ to calculate the
            'breezy.relpath' variable from.
        :param prefix: a prefix to strip from the variable specified in
            path_var before setting 'breezy.relpath'.
        """
        self.app = app
        self.prefix = prefix
        self.path_var = path_var

    def __call__(self, environ, start_response):
        path = environ[self.path_var]
        suffix = '/.bzr/smart'
        if not (path.startswith(self.prefix) and path.endswith(suffix)):
            start_response('404 Not Found', [])
            return []
        environ['breezy.relpath'] = path[len(self.prefix):-len(suffix)]
        return self.app(environ, start_response)


class SmartWSGIApp(object):
    """A WSGI application for the bzr smart server."""

    def __init__(self, backing_transport, root_client_path='/'):
        """Constructor.

        :param backing_transport: a transport.  Requests will be processed
            relative to this transport.
        :param root_client_path: the client path that maps to the root of
            backing_transport.  This is used to interpret relpaths received from
            the client.
        """
        # Use a ChrootServer so that this web application won't
        # accidentally let people access locations they shouldn't.
        # e.g. consider a smart server request for "get /etc/passwd" or
        # something.
        self.chroot_server = chroot.ChrootServer(backing_transport)
        self.chroot_server.start_server()
        self.backing_transport = get_transport(self.chroot_server.get_url())
        self.root_client_path = root_client_path
        # While the chroot server can technically be torn down at this point,
        # as all it does is remove the scheme registration from transport's
        # protocol dictionary, we don't *just in case* there are parts of
        # breezy that will invoke 'get_transport' on urls rather than cloning
        # around the existing transport.
        # self.chroot_server.stop_server()

    def __call__(self, environ, start_response):
        """WSGI application callable."""
        if environ['REQUEST_METHOD'] != 'POST':
            start_response('405 Method not allowed', [('Allow', 'POST')])
            return []

        relpath = environ['breezy.relpath']

        if not relpath.startswith('/'):
            relpath = '/' + relpath
        if not relpath.endswith('/'):
            relpath += '/'

        # Compare the HTTP path (relpath) and root_client_path, and calculate
        # new relpath and root_client_path accordingly, to be used to build the
        # request.
        if relpath.startswith(self.root_client_path):
            # The relpath traverses all of the mandatory root client path.
            # Remove the root_client_path from the relpath, and set
            # adjusted_tcp to None to tell the request handler that no further
            # path translation is required.
            adjusted_rcp = '.'
            adjusted_relpath = relpath[len(self.root_client_path):]
        elif self.root_client_path.startswith(relpath):
            # The relpath traverses some of the mandatory root client path.
            # Subtract the relpath from the root_client_path, and set the
            # relpath to '.'.
            adjusted_rcp = '/' + self.root_client_path[len(relpath):]
            adjusted_relpath = '.'
        else:
            adjusted_rcp = self.root_client_path
            adjusted_relpath = relpath

        if adjusted_relpath.startswith('/'):
            adjusted_relpath = adjusted_relpath[1:]
        if adjusted_relpath.startswith('/'):
            raise AssertionError(adjusted_relpath)

        transport = self.backing_transport.clone(adjusted_relpath)
        out_buffer = BytesIO()
        request_data_length = int(environ['CONTENT_LENGTH'])
        request_data_bytes = environ['wsgi.input'].read(request_data_length)
        smart_protocol_request = self.make_request(
            transport, out_buffer.write, request_data_bytes,
            adjusted_rcp)
        if smart_protocol_request.next_read_size() != 0:
            # The request appears to be incomplete, or perhaps it's just a
            # newer version we don't understand.  Regardless, all we can do
            # is return an error response in the format of our version of the
            # protocol.
            response_data = b'error\x01incomplete request\n'
        else:
            response_data = out_buffer.getvalue()
        headers = [('Content-type', 'application/octet-stream')]
        headers.append(("Content-Length", str(len(response_data))))
        start_response('200 OK', headers)
        return [response_data]

    def make_request(self, transport, write_func, request_bytes, rcp):
        protocol_factory, unused_bytes = medium._get_protocol_factory_for_bytes(
            request_bytes)
        server_protocol = protocol_factory(
            transport, write_func, rcp, self.backing_transport)
        server_protocol.accept_bytes(unused_bytes)
        return server_protocol
