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

"""WSGI application for bzr HTTP smart server.

For more information about WSGI, see PEP 333:
    http://www.python.org/dev/peps/pep-0333/
"""

from cStringIO import StringIO

from bzrlib.transport import get_transport, smart
from bzrlib.urlutils import local_path_to_url
    

def make_app(root, prefix, path_var):
    """Convenience function to construct a WSGI bzr smart server.
    
    :param root: a local path that requests will be relative to.
    :param prefix: See RelpathSetter.
    :param path_var: See RelpathSetter.
    """
    base_transport = get_transport('readonly+' + local_path_to_url(root))
    app = SmartWSGIApp(base_transport)
    app = RelpathSetter(app, prefix, path_var)
    return app


class RelpathSetter(object):
    """WSGI middleware to set 'bzrlib.relpath' in the environ.
    
    Different servers can invoke a SmartWSGIApp in different ways.  This
    middleware allows an adminstrator to configure how to the SmartWSGIApp will
    determine what path it should be serving for a given request for many common
    situations.

    For example, a request for "/some/prefix/repo/branch/.bzr/smart" received by
    a typical Apache and mod_fastcgi configuration will set `REQUEST_URI` to
    "/some/prefix/repo/branch/.bzr/smart".  A RelpathSetter with
    prefix="/some/prefix/" and path_var="REQUEST_URI" will set that request's
    'bzrlib.relpath' variable to "repo/branch".
    """
    
    def __init__(self, app, prefix='', path_var='REQUEST_URI'):
        """Constructor.

        :param app: WSGI app to wrap, e.g. a SmartWSGIApp instance.
        :param path_var: the variable in the WSGI environ to calculate the
            'bzrlib.relpath' variable from.
        :param prefix: a prefix to strip from the variable specified in
            path_var before setting 'bzrlib.relpath'.
        """
        self.app = app
        self.prefix = prefix
        self.path_var = path_var

    def __call__(self, environ, start_response):
        path = environ[self.path_var]
        suffix = '/.bzr/smart'
        if not (path.startswith(self.prefix) and path.endswith(suffix)):
            start_response('404 Not Found', {})
            return []
        environ['bzrlib.relpath'] = path[len(self.prefix):-len(suffix)]
        return self.app(environ, start_response)


class SmartWSGIApp(object):
    """A WSGI application for the bzr smart server."""

    def __init__(self, backing_transport):
        """Constructor.

        :param backing_transport: a transport.  Requests will be processed
            relative to this transport.
        """
        self.backing_transport = backing_transport

    def __call__(self, environ, start_response):
        """WSGI application callable."""
        if environ['REQUEST_METHOD'] != 'POST':
            start_response('405 Method not allowed', [('Allow', 'POST')])
            return []

        relpath = environ['bzrlib.relpath']
        transport = self.backing_transport.clone(relpath)
        #assert transport.base.startswith(self.backing_transport.base)
        out_buffer = StringIO()
        smart_protocol_request = self.make_request(transport, out_buffer.write)
        request_data_length = int(environ['CONTENT_LENGTH'])
        request_data_bytes = environ['wsgi.input'].read(request_data_length)
        smart_protocol_request.accept_bytes(request_data_bytes)
        if smart_protocol_request.next_read_size() != 0:
            # The request appears to be incomplete, or perhaps it's just a
            # newer version we don't understand.  Regardless, all we can do
            # is return an error response in the format of our version of the
            # protocol.
            response_data = 'error\x01incomplete request\n'
        else:
            response_data = out_buffer.getvalue()
        headers = [('Content-type', 'application/octet-stream')]
        headers.append(("Content-Length", str(len(response_data))))
        start_response('200 OK', headers)
        return [response_data]

    def make_request(self, transport, write_func):
        return smart.SmartServerRequestProtocolOne(transport, write_func)
