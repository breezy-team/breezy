# Copyright (C) 2006-2013, 2016, 2017 Canonical Ltd
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

"""Implementation of urllib2 tailored to Breezy's needs

This file complements the urllib2 class hierarchy with custom classes.

For instance, we create a new HTTPConnection and HTTPSConnection that inherit
from the original urllib2.HTTP(s)Connection objects, but also have a new base
which implements a custom getresponse and cleanup_pipe handlers.

And then we implement custom HTTPHandler and HTTPSHandler classes, that use
the custom HTTPConnection classes.

We have a custom Response class, which lets us maintain a keep-alive
connection even for requests that urllib2 doesn't expect to contain body data.

And a custom Request class that lets us track redirections, and
handle authentication schemes.

For coherency with python libraries, we use capitalized header names throughout
the code, even if the header names will be titled just before sending the
request (see AbstractHTTPHandler.do_open).
"""

from __future__ import absolute_import

DEBUG = 0

# FIXME: Oversimplifying, two kind of exceptions should be
# raised, once a request is issued: URLError before we have been
# able to process the response, HTTPError after that. Process the
# response means we are able to leave the socket clean, so if we
# are not able to do that, we should close the connection. The
# actual code more or less do that, tests should be written to
# ensure that.

import base64
import errno
try:
    import http.client as http_client
except ImportError:
    import httplib as http_client
import os
import socket
import urllib
try:
    import urllib.request as urllib_request
except ImportError:  # python < 3
    import urllib2 as urllib_request
try:
    from urllib.parse import urljoin, splitport, splittype, splithost
except ImportError:
    from urlparse import urljoin
    from urllib import splitport, splittype, splithost
import re
import ssl
import sys
import time

from ... import __version__ as breezy_version
from ... import (
    config,
    debug,
    errors,
    lazy_import,
    osutils,
    trace,
    transport,
    ui,
    urlutils,
)
from ...sixish import (
    PY3,
    reraise,
    text_type,
)

try:
    _ = (ssl.match_hostname, ssl.CertificateError)
except AttributeError:
    # Provide fallbacks for python < 2.7.9
    def match_hostname(cert, host):
        trace.warning(
            '%s cannot be verified, https certificates verification is only'
            ' available for python versions >= 2.7.9' % (host,))
    ssl.match_hostname = match_hostname
    ssl.CertificateError = ValueError


# Note for packagers: if there is no package providing certs for your platform,
# the curl project produces http://curl.haxx.se/ca/cacert.pem weekly.
_ssl_ca_certs_known_locations = [
    u'/etc/ssl/certs/ca-certificates.crt',  # Ubuntu/debian/gentoo
    u'/etc/pki/tls/certs/ca-bundle.crt',  # Fedora/CentOS/RH
    u'/etc/ssl/ca-bundle.pem',  # OpenSuse
    u'/etc/ssl/cert.pem',  # OpenSuse
    u"/usr/local/share/certs/ca-root-nss.crt",  # FreeBSD
    # XXX: Needs checking, can't trust the interweb ;) -- vila 2012-01-25
    u'/etc/openssl/certs/ca-certificates.crt',  # Solaris
]


def default_ca_certs():
    if sys.platform == 'win32':
        return os.path.join(os.path.dirname(sys.executable), u"cacert.pem")
    elif sys.platform == 'darwin':
        # FIXME: Needs some default value for osx, waiting for osx installers
        # guys feedback -- vila 2012-01-25
        pass
    else:
        # Try known locations for friendly OSes providing the root certificates
        # without making them hard to use for any https client.
        for path in _ssl_ca_certs_known_locations:
            if os.path.exists(path):
                # First found wins
                return path
    # A default path that makes sense and will be mentioned in the error
    # presented to the user, even if not correct for all platforms
    return _ssl_ca_certs_known_locations[0]


def ca_certs_from_store(path):
    if not os.path.exists(path):
        raise ValueError("ca certs path %s does not exist" % path)
    return path


def cert_reqs_from_store(unicode_str):
    import ssl
    try:
        return {"required": ssl.CERT_REQUIRED,
                "none": ssl.CERT_NONE}[unicode_str]
    except KeyError:
        raise ValueError("invalid value %s" % unicode_str)


def default_ca_reqs():
    if sys.platform in ('win32', 'darwin'):
        # FIXME: Once we get a native access to root certificates there, this
        # won't needed anymore. See http://pad.lv/920455 -- vila 2012-02-15
        return u'none'
    else:
        return u'required'


opt_ssl_ca_certs = config.Option('ssl.ca_certs',
                                 from_unicode=ca_certs_from_store,
                                 default=default_ca_certs,
                                 invalid='warning',
                                 help="""\
Path to certification authority certificates to trust.

This should be a valid path to a bundle containing all root Certificate
Authorities used to verify an https server certificate.

Use ssl.cert_reqs=none to disable certificate verification.
""")

opt_ssl_cert_reqs = config.Option('ssl.cert_reqs',
                                  default=default_ca_reqs,
                                  from_unicode=cert_reqs_from_store,
                                  invalid='error',
                                  help="""\
Whether to require a certificate from the remote side. (default:required)

Possible values:
 * none: Certificates ignored
 * required: Certificates required and validated
""")

checked_kerberos = False
kerberos = None


class addinfourl(urllib_request.addinfourl):
    '''Replacement addinfourl class compatible with python-2.7's xmlrpclib

    In python-2.7, xmlrpclib expects that the response object that it receives
    has a getheader method.  http_client.HTTPResponse provides this but
    urllib_request.addinfourl does not.  Add the necessary functions here, ported to
    use the internal data structures of addinfourl.
    '''

    def getheader(self, name, default=None):
        if self.headers is None:
            raise http_client.ResponseNotReady()
        return self.headers.getheader(name, default)

    def getheaders(self):
        if self.headers is None:
            raise http_client.ResponseNotReady()
        return list(self.headers.items())


class _ReportingFileSocket(object):

    def __init__(self, filesock, report_activity=None):
        self.filesock = filesock
        self._report_activity = report_activity

    def report_activity(self, size, direction):
        if self._report_activity:
            self._report_activity(size, direction)

    def read(self, size=1):
        s = self.filesock.read(size)
        self.report_activity(len(s), 'read')
        return s

    def readline(self, size=-1):
        s = self.filesock.readline(size)
        self.report_activity(len(s), 'read')
        return s

    def readinto(self, b):
        s = self.filesock.readinto(b)
        self.report_activity(s, 'read')
        return s

    def __getattr__(self, name):
        return getattr(self.filesock, name)


class _ReportingSocket(object):

    def __init__(self, sock, report_activity=None):
        self.sock = sock
        self._report_activity = report_activity

    def report_activity(self, size, direction):
        if self._report_activity:
            self._report_activity(size, direction)

    def sendall(self, s, *args):
        self.sock.sendall(s, *args)
        self.report_activity(len(s), 'write')

    def recv(self, *args):
        s = self.sock.recv(*args)
        self.report_activity(len(s), 'read')
        return s

    def makefile(self, mode='r', bufsize=-1):
        # http_client creates a fileobject that doesn't do buffering, which
        # makes fp.readline() very expensive because it only reads one byte
        # at a time.  So we wrap the socket in an object that forces
        # sock.makefile to make a buffered file.
        fsock = self.sock.makefile(mode, 65536)
        # And wrap that into a reporting kind of fileobject
        return _ReportingFileSocket(fsock, self._report_activity)

    def __getattr__(self, name):
        return getattr(self.sock, name)


# We define our own Response class to keep our http_client pipe clean
class Response(http_client.HTTPResponse):
    """Custom HTTPResponse, to avoid the need to decorate.

    http_client prefers to decorate the returned objects, rather
    than using a custom object.
    """

    # Some responses have bodies in which we have no interest
    _body_ignored_responses = [301, 302, 303, 307, 400, 401, 403, 404, 501]

    # in finish() below, we may have to discard several MB in the worst
    # case. To avoid buffering that much, we read and discard by chunks
    # instead. The underlying file is either a socket or a StringIO, so reading
    # 8k chunks should be fine.
    _discarded_buf_size = 8192

    if PY3:
        def __init__(self, sock, debuglevel=0, method=None, url=None):
            self.url = url
            super(Response, self).__init__(
                sock, debuglevel=debuglevel, method=method, url=url)

    def begin(self):
        """Begin to read the response from the server.

        http_client assumes that some responses get no content and do
        not even attempt to read the body in that case, leaving
        the body in the socket, blocking the next request. Let's
        try to workaround that.
        """
        http_client.HTTPResponse.begin(self)
        if self.status in self._body_ignored_responses:
            if self.debuglevel >= 2:
                print("For status: [%s], will ready body, length: %s" % (
                    self.status, self.length))
            if not (self.length is None or self.will_close):
                # In some cases, we just can't read the body not
                # even try or we may encounter a 104, 'Connection
                # reset by peer' error if there is indeed no body
                # and the server closed the connection just after
                # having issued the response headers (even if the
                # headers indicate a Content-Type...)
                body = self.read(self.length)
                if self.debuglevel >= 9:
                    # This one can be huge and is generally not interesting
                    print("Consumed body: [%s]" % body)
            self.close()
        elif self.status == 200:
            # Whatever the request is, it went ok, so we surely don't want to
            # close the connection. Some cases are not correctly detected by
            # http_client.HTTPConnection.getresponse (called by
            # http_client.HTTPResponse.begin). The CONNECT response for the https
            # through proxy case is one.  Note: the 'will_close' below refers
            # to the "true" socket between us and the server, whereas the
            # 'close()' above refers to the copy of that socket created by
            # http_client for the response itself. So, in the if above we close the
            # socket to indicate that we are done with the response whereas
            # below we keep the socket with the server opened.
            self.will_close = False

    def finish(self):
        """Finish reading the body.

        In some cases, the client may have left some bytes to read in the
        body. That will block the next request to succeed if we use a
        persistent connection. If we don't use a persistent connection, well,
        nothing will block the next request since a new connection will be
        issued anyway.

        :return: the number of bytes left on the socket (may be None)
        """
        pending = None
        if not self.isclosed():
            # Make sure nothing was left to be read on the socket
            pending = 0
            data = True
            while data and self.length:
                # read() will update self.length
                data = self.read(min(self.length, self._discarded_buf_size))
                pending += len(data)
            if pending:
                trace.mutter("%s bytes left on the HTTP socket", pending)
            self.close()
        return pending


# Not inheriting from 'object' because http_client.HTTPConnection doesn't.
class AbstractHTTPConnection:
    """A custom HTTP(S) Connection, which can reset itself on a bad response"""

    response_class = Response

    # When we detect a server responding with the whole file to range requests,
    # we want to warn. But not below a given thresold.
    _range_warning_thresold = 1024 * 1024

    def __init__(self, report_activity=None):
        self._response = None
        self._report_activity = report_activity
        self._ranges_received_whole_file = None

    def _mutter_connect(self):
        netloc = '%s:%s' % (self.host, self.port)
        if self.proxied_host is not None:
            netloc += '(proxy for %s)' % self.proxied_host
        trace.mutter('* About to connect() to %s' % netloc)

    def getresponse(self):
        """Capture the response to be able to cleanup"""
        self._response = http_client.HTTPConnection.getresponse(self)
        return self._response

    def cleanup_pipe(self):
        """Read the remaining bytes of the last response if any."""
        if self._response is not None:
            try:
                pending = self._response.finish()
                # Warn the user (once)
                if (self._ranges_received_whole_file is None
                        and self._response.status == 200
                        and pending
                        and pending > self._range_warning_thresold):
                    self._ranges_received_whole_file = True
                    trace.warning(
                        'Got a 200 response when asking for multiple ranges,'
                        ' does your server at %s:%s support range requests?',
                        self.host, self.port)
            except socket.error as e:
                # It's conceivable that the socket is in a bad state here
                # (including some test cases) and in this case, it doesn't need
                # cleaning anymore, so no need to fail, we just get rid of the
                # socket and let callers reconnect
                if (len(e.args) == 0
                        or e.args[0] not in (errno.ECONNRESET, errno.ECONNABORTED)):
                    raise
                self.close()
            self._response = None
        # Preserve our preciousss
        sock = self.sock
        self.sock = None
        # Let http_client.HTTPConnection do its housekeeping
        self.close()
        # Restore our preciousss
        self.sock = sock

    def _wrap_socket_for_reporting(self, sock):
        """Wrap the socket before anybody use it."""
        self.sock = _ReportingSocket(sock, self._report_activity)


class HTTPConnection(AbstractHTTPConnection, http_client.HTTPConnection):

    # XXX: Needs refactoring at the caller level.
    def __init__(self, host, port=None, proxied_host=None,
                 report_activity=None, ca_certs=None):
        AbstractHTTPConnection.__init__(self, report_activity=report_activity)
        if PY3:
            http_client.HTTPConnection.__init__(self, host, port)
        else:
            # Use strict=True since we don't support HTTP/0.9
            http_client.HTTPConnection.__init__(self, host, port, strict=True)
        self.proxied_host = proxied_host
        # ca_certs is ignored, it's only relevant for https

    def connect(self):
        if 'http' in debug.debug_flags:
            self._mutter_connect()
        http_client.HTTPConnection.connect(self)
        self._wrap_socket_for_reporting(self.sock)


class HTTPSConnection(AbstractHTTPConnection, http_client.HTTPSConnection):

    def __init__(self, host, port=None, key_file=None, cert_file=None,
                 proxied_host=None,
                 report_activity=None, ca_certs=None):
        AbstractHTTPConnection.__init__(self, report_activity=report_activity)
        if PY3:
            http_client.HTTPSConnection.__init__(
                self, host, port, key_file, cert_file)
        else:
            # Use strict=True since we don't support HTTP/0.9
            http_client.HTTPSConnection.__init__(self, host, port,
                                                 key_file, cert_file, strict=True)
        self.proxied_host = proxied_host
        self.ca_certs = ca_certs

    def connect(self):
        if 'http' in debug.debug_flags:
            self._mutter_connect()
        http_client.HTTPConnection.connect(self)
        self._wrap_socket_for_reporting(self.sock)
        if self.proxied_host is None:
            self.connect_to_origin()

    def connect_to_origin(self):
        # FIXME JRV 2011-12-18: Use location config here?
        config_stack = config.GlobalStack()
        cert_reqs = config_stack.get('ssl.cert_reqs')
        if self.proxied_host is not None:
            host = self.proxied_host.split(":", 1)[0]
        else:
            host = self.host
        if cert_reqs == ssl.CERT_NONE:
            ui.ui_factory.show_user_warning('not_checking_ssl_cert', host=host)
            ui.ui_factory.suppressed_warnings.add('not_checking_ssl_cert')
            ca_certs = None
        else:
            if self.ca_certs is None:
                ca_certs = config_stack.get('ssl.ca_certs')
            else:
                ca_certs = self.ca_certs
            if ca_certs is None:
                trace.warning(
                    "No valid trusted SSL CA certificates file set. See "
                    "'brz help ssl.ca_certs' for more information on setting "
                    "trusted CAs.")
        try:
            ssl_context = ssl.create_default_context(
                purpose=ssl.Purpose.SERVER_AUTH, cafile=ca_certs)
            ssl_context.check_hostname = cert_reqs != ssl.CERT_NONE
            if self.cert_file:
                ssl_context.load_cert_chain(
                    keyfile=self.key_file, certfile=self.cert_file)
            ssl_context.verify_mode = cert_reqs
            ssl_sock = ssl_context.wrap_socket(
                self.sock, server_hostname=self.host)
        except ssl.SSLError:
            trace.note(
                "\n"
                "See `brz help ssl.ca_certs` for how to specify trusted CA"
                "certificates.\n"
                "Pass -Ossl.cert_reqs=none to disable certificate "
                "verification entirely.\n")
            raise
        # Wrap the ssl socket before anybody use it
        self._wrap_socket_for_reporting(ssl_sock)


class Request(urllib_request.Request):
    """A custom Request object.

    urllib_request determines the request method heuristically (based on
    the presence or absence of data). We set the method
    statically.

    The Request object tracks:
    - the connection the request will be made on.
    - the authentication parameters needed to preventively set
      the authentication header once a first authentication have
       been made.
    """

    def __init__(self, method, url, data=None, headers={},
                 origin_req_host=None, unverifiable=False,
                 connection=None, parent=None,
                 accepted_errors=None):
        urllib_request.Request.__init__(
            self, url, data, headers,
            origin_req_host, unverifiable)
        self.method = method
        self.connection = connection
        self.accepted_errors = accepted_errors
        # To handle redirections
        self.parent = parent
        self.redirected_to = None
        # Unless told otherwise, redirections are not followed
        self.follow_redirections = False
        # auth and proxy_auth are dicts containing, at least
        # (scheme, host, port, realm, user, password, protocol, path).
        # The dict entries are mostly handled by the AuthHandler.
        # Some authentication schemes may add more entries.
        self.auth = {}
        self.proxy_auth = {}
        self.proxied_host = None

    def get_method(self):
        return self.method

    def set_proxy(self, proxy, type):
        """Set the proxy and remember the proxied host."""
        if PY3:
            host, port = splitport(self.host)
        else:
            host, port = splitport(self.get_host())
        if port is None:
            # We need to set the default port ourselves way before it gets set
            # in the HTTP[S]Connection object at build time.
            if self.type == 'https':
                conn_class = HTTPSConnection
            else:
                conn_class = HTTPConnection
            port = conn_class.default_port
        self.proxied_host = '%s:%s' % (host, port)
        urllib_request.Request.set_proxy(self, proxy, type)
        # When urllib_request makes a https request with our wrapper code and a proxy,
        # it sets Host to the https proxy, not the host we want to talk to.
        # I'm fairly sure this is our fault, but what is the cause is an open
        # question. -- Robert Collins May 8 2010.
        self.add_unredirected_header('Host', self.proxied_host)


class _ConnectRequest(Request):

    def __init__(self, request):
        """Constructor

        :param request: the first request sent to the proxied host, already
            processed by the opener (i.e. proxied_host is already set).
        """
        # We give a fake url and redefine selector or urllib_request will be
        # confused
        Request.__init__(self, 'CONNECT', request.get_full_url(),
                         connection=request.connection)
        if request.proxied_host is None:
            raise AssertionError()
        self.proxied_host = request.proxied_host

    @property
    def selector(self):
        return self.proxied_host

    def get_selector(self):
        return self.selector

    def set_proxy(self, proxy, type):
        """Set the proxy without remembering the proxied host.

        We already know the proxied host by definition, the CONNECT request
        occurs only when the connection goes through a proxy. The usual
        processing (masquerade the request so that the connection is done to
        the proxy while the request is targeted at another host) does not apply
        here. In fact, the connection is already established with proxy and we
        just want to enable the SSL tunneling.
        """
        urllib_request.Request.set_proxy(self, proxy, type)


class ConnectionHandler(urllib_request.BaseHandler):
    """Provides connection-sharing by pre-processing requests.

    urllib_request provides no way to access the HTTPConnection object
    internally used. But we need it in order to achieve
    connection sharing. So, we add it to the request just before
    it is processed, and then we override the do_open method for
    http[s] requests in AbstractHTTPHandler.
    """

    handler_order = 1000  # after all pre-processings

    def __init__(self, report_activity=None, ca_certs=None):
        self._report_activity = report_activity
        self.ca_certs = ca_certs

    def create_connection(self, request, http_connection_class):
        host = request.host
        if not host:
            # Just a bit of paranoia here, this should have been
            # handled in the higher levels
            raise urlutils.InvalidURL(request.get_full_url(), 'no host given.')

        # We create a connection (but it will not connect until the first
        # request is made)
        try:
            connection = http_connection_class(
                host, proxied_host=request.proxied_host,
                report_activity=self._report_activity,
                ca_certs=self.ca_certs)
        except http_client.InvalidURL as exception:
            # There is only one occurrence of InvalidURL in http_client
            raise urlutils.InvalidURL(request.get_full_url(),
                                      extra='nonnumeric port')

        return connection

    def capture_connection(self, request, http_connection_class):
        """Capture or inject the request connection.

        Two cases:
        - the request have no connection: create a new one,

        - the request have a connection: this one have been used
          already, let's capture it, so that we can give it to
          another transport to be reused. We don't do that
          ourselves: the Transport object get the connection from
          a first request and then propagate it, from request to
          request or to cloned transports.
        """
        connection = request.connection
        if connection is None:
            # Create a new one
            connection = self.create_connection(request, http_connection_class)
            request.connection = connection

        # All connections will pass here, propagate debug level
        connection.set_debuglevel(DEBUG)
        return request

    def http_request(self, request):
        return self.capture_connection(request, HTTPConnection)

    def https_request(self, request):
        return self.capture_connection(request, HTTPSConnection)


class AbstractHTTPHandler(urllib_request.AbstractHTTPHandler):
    """A custom handler for HTTP(S) requests.

    We overrive urllib_request.AbstractHTTPHandler to get a better
    control of the connection, the ability to implement new
    request types and return a response able to cope with
    persistent connections.
    """

    # We change our order to be before urllib_request HTTP[S]Handlers
    # and be chosen instead of them (the first http_open called
    # wins).
    handler_order = 400

    _default_headers = {'Pragma': 'no-cache',
                        'Cache-control': 'max-age=0',
                        'Connection': 'Keep-Alive',
                        'User-agent': 'Breezy/%s' % breezy_version,
                        'Accept': '*/*',
                        }

    def __init__(self):
        urllib_request.AbstractHTTPHandler.__init__(self, debuglevel=DEBUG)

    def http_request(self, request):
        """Common headers setting"""

        for name, value in self._default_headers.items():
            if name not in request.headers:
                request.headers[name] = value
        # FIXME: We may have to add the Content-Length header if
        # we have data to send.
        return request

    def retry_or_raise(self, http_class, request, first_try):
        """Retry the request (once) or raise the exception.

        urllib_request raises exception of application level kind, we
        just have to translate them.

        http_client can raise exceptions of transport level (badly
        formatted dialog, loss of connexion or socket level
        problems). In that case we should issue the request again
        (http_client will close and reopen a new connection if
        needed).
        """
        # When an exception occurs, we give back the original
        # Traceback or the bugs are hard to diagnose.
        exc_type, exc_val, exc_tb = sys.exc_info()
        if exc_type == socket.gaierror:
            # No need to retry, that will not help
            if PY3:
                origin_req_host = request.origin_req_host
            else:
                origin_req_host = request.get_origin_req_host()
            raise errors.ConnectionError("Couldn't resolve host '%s'"
                                         % origin_req_host,
                                         orig_error=exc_val)
        elif isinstance(exc_val, http_client.ImproperConnectionState):
            # The http_client pipeline is in incorrect state, it's a bug in our
            # implementation.
            reraise(exc_type, exc_val, exc_tb)
        else:
            if first_try:
                if self._debuglevel >= 2:
                    print('Received exception: [%r]' % exc_val)
                    print('  On connection: [%r]' % request.connection)
                    method = request.get_method()
                    url = request.get_full_url()
                    print('  Will retry, %s %r' % (method, url))
                request.connection.close()
                response = self.do_open(http_class, request, False)
            else:
                if self._debuglevel >= 2:
                    print('Received second exception: [%r]' % exc_val)
                    print('  On connection: [%r]' % request.connection)
                if exc_type in (http_client.BadStatusLine, http_client.UnknownProtocol):
                    # http_client.BadStatusLine and
                    # http_client.UnknownProtocol indicates that a
                    # bogus server was encountered or a bad
                    # connection (i.e. transient errors) is
                    # experimented, we have already retried once
                    # for that request so we raise the exception.
                    my_exception = errors.InvalidHttpResponse(
                        request.get_full_url(),
                        'Bad status line received',
                        orig_error=exc_val)
                elif (isinstance(exc_val, socket.error) and len(exc_val.args)
                      and exc_val.args[0] in (errno.ECONNRESET, 10053, 10054)):
                    # 10053 == WSAECONNABORTED
                    # 10054 == WSAECONNRESET
                    raise errors.ConnectionReset(
                        "Connection lost while sending request.")
                else:
                    # All other exception are considered connection related.

                    # socket errors generally occurs for reasons
                    # far outside our scope, so closing the
                    # connection and retrying is the best we can
                    # do.
                    if PY3:
                        selector = request.selector
                    else:
                        selector = request.get_selector()
                    my_exception = errors.ConnectionError(
                        msg='while sending %s %s:' % (request.get_method(),
                                                      selector),
                        orig_error=exc_val)

                if self._debuglevel >= 2:
                    print('On connection: [%r]' % request.connection)
                    method = request.get_method()
                    url = request.get_full_url()
                    print('  Failed again, %s %r' % (method, url))
                    print('  Will raise: [%r]' % my_exception)
                reraise(type(my_exception), my_exception, exc_tb)
        return response

    def do_open(self, http_class, request, first_try=True):
        """See urllib_request.AbstractHTTPHandler.do_open for the general idea.

        The request will be retried once if it fails.
        """
        connection = request.connection
        if connection is None:
            raise AssertionError(
                'Cannot process a request without a connection')

        # Get all the headers
        headers = {}
        headers.update(request.header_items())
        headers.update(request.unredirected_hdrs)
        # Some servers or proxies will choke on headers not properly
        # cased. http_client/urllib/urllib_request all use capitalize to get canonical
        # header names, but only python2.5 urllib_request use title() to fix them just
        # before sending the request. And not all versions of python 2.5 do
        # that. Since we replace urllib_request.AbstractHTTPHandler.do_open we do it
        # ourself below.
        headers = {name.title(): val for name, val in headers.items()}

        try:
            method = request.get_method()
            if PY3:
                url = request.selector
            else:
                url = request.get_selector()
            if sys.version_info[:2] >= (3, 6):
                connection._send_request(method, url,
                                         # FIXME: implements 100-continue
                                         # None, # We don't send the body yet
                                         request.data,
                                         headers, encode_chunked=False)
            else:
                connection._send_request(method, url,
                                         # FIXME: implements 100-continue
                                         # None, # We don't send the body yet
                                         request.data,
                                         headers)
            if 'http' in debug.debug_flags:
                trace.mutter('> %s %s' % (method, url))
                hdrs = []
                for k, v in headers.items():
                    # People are often told to paste -Dhttp output to help
                    # debug. Don't compromise credentials.
                    if k in ('Authorization', 'Proxy-Authorization'):
                        v = '<masked>'
                    hdrs.append('%s: %s' % (k, v))
                trace.mutter('> ' + '\n> '.join(hdrs) + '\n')
            if self._debuglevel >= 1:
                print('Request sent: [%r] from (%s)'
                      % (request, request.connection.sock.getsockname()))
            response = connection.getresponse()
            convert_to_addinfourl = True
        except (ssl.SSLError, ssl.CertificateError):
            # Something is wrong with either the certificate or the hostname,
            # re-trying won't help
            raise
        except (socket.gaierror, http_client.BadStatusLine, http_client.UnknownProtocol,
                socket.error, http_client.HTTPException):
            response = self.retry_or_raise(http_class, request, first_try)
            convert_to_addinfourl = False

        if PY3:
            response.msg = response.reason
            return response

# FIXME: HTTPConnection does not fully support 100-continue (the
# server responses are just ignored)

#        if code == 100:
#            mutter('Will send the body')
#            # We can send the body now
#            body = request.data
#            if body is None:
#                raise URLError("No data given")
#            connection.send(body)
#            response = connection.getresponse()

        if self._debuglevel >= 2:
            print('Receives response: %r' % response)
            print('  For: %r(%r)' % (request.get_method(),
                                     request.get_full_url()))

        if convert_to_addinfourl:
            # Shamelessly copied from urllib_request
            req = request
            r = response
            r.recv = r.read
            fp = socket._fileobject(r, bufsize=65536)
            resp = addinfourl(fp, r.msg, req.get_full_url())
            resp.code = r.status
            resp.msg = r.reason
            resp.version = r.version
            if self._debuglevel >= 2:
                print('Create addinfourl: %r' % resp)
                print('  For: %r(%r)' % (request.get_method(),
                                         request.get_full_url()))
            if 'http' in debug.debug_flags:
                version = 'HTTP/%d.%d'
                try:
                    version = version % (resp.version / 10,
                                         resp.version % 10)
                except:
                    version = 'HTTP/%r' % resp.version
                trace.mutter('< %s %s %s' % (version, resp.code,
                                             resp.msg))
                # Use the raw header lines instead of treating resp.info() as a
                # dict since we may miss duplicated headers otherwise.
                hdrs = [h.rstrip('\r\n') for h in resp.info().headers]
                trace.mutter('< ' + '\n< '.join(hdrs) + '\n')
        else:
            resp = response
        return resp


class HTTPHandler(AbstractHTTPHandler):
    """A custom handler that just thunks into HTTPConnection"""

    def http_open(self, request):
        return self.do_open(HTTPConnection, request)


class HTTPSHandler(AbstractHTTPHandler):
    """A custom handler that just thunks into HTTPSConnection"""

    https_request = AbstractHTTPHandler.http_request

    def https_open(self, request):
        connection = request.connection
        if connection.sock is None and \
                connection.proxied_host is not None and \
                request.get_method() != 'CONNECT':  # Don't loop
            # FIXME: We need a gazillion connection tests here, but we still
            # miss a https server :-( :
            # - with and without proxy
            # - with and without certificate
            # - with self-signed certificate
            # - with and without authentication
            # - with good and bad credentials (especially the proxy auth around
            #   CONNECT)
            # - with basic and digest schemes
            # - reconnection on errors
            # - connection persistence behaviour (including reconnection)

            # We are about to connect for the first time via a proxy, we must
            # issue a CONNECT request first to establish the encrypted link
            connect = _ConnectRequest(request)
            response = self.parent.open(connect)
            if response.code != 200:
                raise errors.ConnectionError("Can't connect to %s via proxy %s" % (
                    connect.proxied_host, self.host))
            # Housekeeping
            connection.cleanup_pipe()
            # Establish the connection encryption
            connection.connect_to_origin()
            # Propagate the connection to the original request
            request.connection = connection
        return self.do_open(HTTPSConnection, request)


class HTTPRedirectHandler(urllib_request.HTTPRedirectHandler):
    """Handles redirect requests.

    We have to implement our own scheme because we use a specific
    Request object and because we want to implement a specific
    policy.
    """
    _debuglevel = DEBUG
    # RFC2616 says that only read requests should be redirected
    # without interacting with the user. But Breezy uses some
    # shortcuts to optimize against roundtrips which can leads to
    # write requests being issued before read requests of
    # containing dirs can be redirected. So we redirect write
    # requests in the same way which seems to respect the spirit
    # of the RFC if not its letter.

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """See urllib_request.HTTPRedirectHandler.redirect_request"""
        # We would have preferred to update the request instead
        # of creating a new one, but the urllib_request.Request object
        # has a too complicated creation process to provide a
        # simple enough equivalent update process. Instead, when
        # redirecting, we only update the following request in
        # the redirect chain with a reference to the parent
        # request .

        # Some codes make no sense in our context and are treated
        # as errors:

        # 300: Multiple choices for different representations of
        #      the URI. Using that mechanisn with Breezy will violate the
        #      protocol neutrality of Transport.

        # 304: Not modified (SHOULD only occurs with conditional
        #      GETs which are not used by our implementation)

        # 305: Use proxy. I can't imagine this one occurring in
        #      our context-- vila/20060909

        # 306: Unused (if the RFC says so...)

        # If the code is 302 and the request is HEAD, some may
        # think that it is a sufficent hint that the file exists
        # and that we MAY avoid following the redirections. But
        # if we want to be sure, we MUST follow them.

        if PY3:
            origin_req_host = req.origin_req_host
        else:
            origin_req_host = req.get_origin_req_host()

        if code in (301, 302, 303, 307):
            return Request(req.get_method(), newurl,
                           headers=req.headers,
                           origin_req_host=origin_req_host,
                           unverifiable=True,
                           # TODO: It will be nice to be able to
                           # detect virtual hosts sharing the same
                           # IP address, that will allow us to
                           # share the same connection...
                           connection=None,
                           parent=req,
                           )
        else:
            raise urllib_request.HTTPError(
                req.get_full_url(), code, msg, headers, fp)

    def http_error_302(self, req, fp, code, msg, headers):
        """Requests the redirected to URI.

        Copied from urllib_request to be able to clean the pipe of the associated
        connection, *before* issuing the redirected request but *after* having
        eventually raised an error.
        """
        # Some servers (incorrectly) return multiple Location headers
        # (so probably same goes for URI).  Use first header.

        # TODO: Once we get rid of addinfourl objects, the
        # following will need to be updated to use correct case
        # for headers.
        if 'location' in headers:
            newurl = headers.get('location')
        elif 'uri' in headers:
            newurl = headers.get('uri')
        else:
            return
        if self._debuglevel >= 1:
            print('Redirected to: %s (followed: %r)' % (newurl,
                                                        req.follow_redirections))
        if req.follow_redirections is False:
            req.redirected_to = newurl
            return fp

        newurl = urljoin(req.get_full_url(), newurl)

        # This call succeeds or raise an error. urllib_request returns
        # if redirect_request returns None, but our
        # redirect_request never returns None.
        redirected_req = self.redirect_request(req, fp, code, msg, headers,
                                               newurl)

        # loop detection
        # .redirect_dict has a key url if url was previously visited.
        if hasattr(req, 'redirect_dict'):
            visited = redirected_req.redirect_dict = req.redirect_dict
            if (visited.get(newurl, 0) >= self.max_repeats or
                    len(visited) >= self.max_redirections):
                raise urllib_request.HTTPError(req.get_full_url(), code,
                                               self.inf_msg + msg, headers, fp)
        else:
            visited = redirected_req.redirect_dict = req.redirect_dict = {}
        visited[newurl] = visited.get(newurl, 0) + 1

        # We can close the fp now that we are sure that we won't
        # use it with HTTPError.
        fp.close()
        # We have all we need already in the response
        req.connection.cleanup_pipe()

        return self.parent.open(redirected_req)

    http_error_301 = http_error_303 = http_error_307 = http_error_302


class ProxyHandler(urllib_request.ProxyHandler):
    """Handles proxy setting.

    Copied and modified from urllib_request to be able to modify the request during
    the request pre-processing instead of modifying it at _open time. As we
    capture (or create) the connection object during request processing, _open
    time was too late.

    The main task is to modify the request so that the connection is done to
    the proxy while the request still refers to the destination host.

    Note: the proxy handling *may* modify the protocol used; the request may be
    against an https server proxied through an http proxy. So, https_request
    will be called, but later it's really http_open that will be called. This
    explains why we don't have to call self.parent.open as the urllib_request did.
    """

    # Proxies must be in front
    handler_order = 100
    _debuglevel = DEBUG

    def __init__(self, proxies=None):
        urllib_request.ProxyHandler.__init__(self, proxies)
        # First, let's get rid of urllib_request implementation
        for type, proxy in self.proxies.items():
            if self._debuglevel >= 3:
                print('Will unbind %s_open for %r' % (type, proxy))
            delattr(self, '%s_open' % type)

        def bind_scheme_request(proxy, scheme):
            if proxy is None:
                return
            scheme_request = scheme + '_request'
            if self._debuglevel >= 3:
                print('Will bind %s for %r' % (scheme_request, proxy))
            setattr(self, scheme_request,
                    lambda request: self.set_proxy(request, scheme))
        # We are interested only by the http[s] proxies
        http_proxy = self.get_proxy_env_var('http')
        bind_scheme_request(http_proxy, 'http')
        https_proxy = self.get_proxy_env_var('https')
        bind_scheme_request(https_proxy, 'https')

    def get_proxy_env_var(self, name, default_to='all'):
        """Get a proxy env var.

        Note that we indirectly rely on
        urllib.getproxies_environment taking into account the
        uppercased values for proxy variables.
        """
        try:
            return self.proxies[name.lower()]
        except KeyError:
            if default_to is not None:
                # Try to get the alternate environment variable
                try:
                    return self.proxies[default_to]
                except KeyError:
                    pass
        return None

    def proxy_bypass(self, host):
        """Check if host should be proxied or not.

        :returns: True to skip the proxy, False otherwise.
        """
        no_proxy = self.get_proxy_env_var('no', default_to=None)
        bypass = self.evaluate_proxy_bypass(host, no_proxy)
        if bypass is None:
            # Nevertheless, there are platform-specific ways to
            # ignore proxies...
            return urllib.proxy_bypass(host)
        else:
            return bypass

    def evaluate_proxy_bypass(self, host, no_proxy):
        """Check the host against a comma-separated no_proxy list as a string.

        :param host: ``host:port`` being requested

        :param no_proxy: comma-separated list of hosts to access directly.

        :returns: True to skip the proxy, False not to, or None to
            leave it to urllib.
        """
        if no_proxy is None:
            # All hosts are proxied
            return False
        hhost, hport = splitport(host)
        # Does host match any of the domains mentioned in
        # no_proxy ? The rules about what is authorized in no_proxy
        # are fuzzy (to say the least). We try to allow most
        # commonly seen values.
        for domain in no_proxy.split(','):
            domain = domain.strip()
            if domain == '':
                continue
            dhost, dport = splitport(domain)
            if hport == dport or dport is None:
                # Protect glob chars
                dhost = dhost.replace(".", r"\.")
                dhost = dhost.replace("*", r".*")
                dhost = dhost.replace("?", r".")
                if re.match(dhost, hhost, re.IGNORECASE):
                    return True
        # Nothing explicitly avoid the host
        return None

    def set_proxy(self, request, type):
        if PY3:
            host = request.host
        else:
            host = request.get_host()
        if self.proxy_bypass(host):
            return request

        proxy = self.get_proxy_env_var(type)
        if self._debuglevel >= 3:
            print('set_proxy %s_request for %r' % (type, proxy))
        # FIXME: python 2.5 urlparse provides a better _parse_proxy which can
        # grok user:password@host:port as well as
        # http://user:password@host:port

        parsed_url = transport.ConnectedTransport._split_url(proxy)
        if not parsed_url.host:
            raise urlutils.InvalidURL(proxy, 'No host component')

        if request.proxy_auth == {}:
            # No proxy auth parameter are available, we are handling the first
            # proxied request, intialize.  scheme (the authentication scheme)
            # and realm will be set by the AuthHandler
            request.proxy_auth = {
                'host': parsed_url.host,
                'port': parsed_url.port,
                'user': parsed_url.user,
                'password': parsed_url.password,
                'protocol': parsed_url.scheme,
                # We ignore path since we connect to a proxy
                'path': None}
        if parsed_url.port is None:
            phost = parsed_url.host
        else:
            phost = parsed_url.host + ':%d' % parsed_url.port
        request.set_proxy(phost, type)
        if self._debuglevel >= 3:
            print('set_proxy: proxy set to %s://%s' % (type, phost))
        return request


class AbstractAuthHandler(urllib_request.BaseHandler):
    """A custom abstract authentication handler for all http authentications.

    Provides the meat to handle authentication errors and
    preventively set authentication headers after the first
    successful authentication.

    This can be used for http and proxy, as well as for basic, negotiate and
    digest authentications.

    This provides an unified interface for all authentication handlers
    (urllib_request provides far too many with different policies).

    The interaction between this handler and the urllib_request
    framework is not obvious, it works as follow:

    opener.open(request) is called:

    - that may trigger http_request which will add an authentication header
      (self.build_header) if enough info is available.

    - the request is sent to the server,

    - if an authentication error is received self.auth_required is called,
      we acquire the authentication info in the error headers and call
      self.auth_match to check that we are able to try the
      authentication and complete the authentication parameters,

    - we call parent.open(request), that may trigger http_request
      and will add a header (self.build_header), but here we have
      all the required info (keep in mind that the request and
      authentication used in the recursive calls are really (and must be)
      the *same* objects).

    - if the call returns a response, the authentication have been
      successful and the request authentication parameters have been updated.
    """

    scheme = None
    """The scheme as it appears in the server header (lower cased)"""

    _max_retry = 3
    """We don't want to retry authenticating endlessly"""

    requires_username = True
    """Whether the auth mechanism requires a username."""

    # The following attributes should be defined by daughter
    # classes:
    # - auth_required_header:  the header received from the server
    # - auth_header: the header sent in the request

    def __init__(self):
        # We want to know when we enter into an try/fail cycle of
        # authentications so we initialize to None to indicate that we aren't
        # in such a cycle by default.
        self._retry_count = None

    def _parse_auth_header(self, server_header):
        """Parse the authentication header.

        :param server_header: The value of the header sent by the server
            describing the authenticaion request.

        :return: A tuple (scheme, remainder) scheme being the first word in the
            given header (lower cased), remainder may be None.
        """
        try:
            scheme, remainder = server_header.split(None, 1)
        except ValueError:
            scheme = server_header
            remainder = None
        return (scheme.lower(), remainder)

    def update_auth(self, auth, key, value):
        """Update a value in auth marking the auth as modified if needed"""
        old_value = auth.get(key, None)
        if old_value != value:
            auth[key] = value
            auth['modified'] = True

    def auth_required(self, request, headers):
        """Retry the request if the auth scheme is ours.

        :param request: The request needing authentication.
        :param headers: The headers for the authentication error response.
        :return: None or the response for the authenticated request.
        """
        # Don't try  to authenticate endlessly
        if self._retry_count is None:
            # The retry being recusrsive calls, None identify the first retry
            self._retry_count = 1
        else:
            self._retry_count += 1
            if self._retry_count > self._max_retry:
                # Let's be ready for next round
                self._retry_count = None
                return None
        if PY3:
            server_headers = headers.get_all(self.auth_required_header)
        else:
            server_headers = headers.getheaders(self.auth_required_header)
        if not server_headers:
            # The http error MUST have the associated
            # header. This must never happen in production code.
            raise KeyError('%s not found' % self.auth_required_header)

        auth = self.get_auth(request)
        auth['modified'] = False
        # Put some common info in auth if the caller didn't
        if auth.get('path', None) is None:
            parsed_url = urlutils.URL.from_string(request.get_full_url())
            self.update_auth(auth, 'protocol', parsed_url.scheme)
            self.update_auth(auth, 'host', parsed_url.host)
            self.update_auth(auth, 'port', parsed_url.port)
            self.update_auth(auth, 'path', parsed_url.path)
        # FIXME: the auth handler should be selected at a single place instead
        # of letting all handlers try to match all headers, but the current
        # design doesn't allow a simple implementation.
        for server_header in server_headers:
            # Several schemes can be proposed by the server, try to match each
            # one in turn
            matching_handler = self.auth_match(server_header, auth)
            if matching_handler:
                # auth_match may have modified auth (by adding the
                # password or changing the realm, for example)
                if (request.get_header(self.auth_header, None) is not None
                        and not auth['modified']):
                    # We already tried that, give up
                    return None

                # Only the most secure scheme proposed by the server should be
                # used, since the handlers use 'handler_order' to describe that
                # property, the first handler tried takes precedence, the
                # others should not attempt to authenticate if the best one
                # failed.
                best_scheme = auth.get('best_scheme', None)
                if best_scheme is None:
                    # At that point, if current handler should doesn't succeed
                    # the credentials are wrong (or incomplete), but we know
                    # that the associated scheme should be used.
                    best_scheme = auth['best_scheme'] = self.scheme
                if best_scheme != self.scheme:
                    continue

                if self.requires_username and auth.get('user', None) is None:
                    # Without a known user, we can't authenticate
                    return None

                # Housekeeping
                request.connection.cleanup_pipe()
                # Retry the request with an authentication header added
                response = self.parent.open(request)
                if response:
                    self.auth_successful(request, response)
                return response
        # We are not qualified to handle the authentication.
        # Note: the authentication error handling will try all
        # available handlers. If one of them authenticates
        # successfully, a response will be returned. If none of
        # them succeeds, None will be returned and the error
        # handler will raise the 401 'Unauthorized' or the 407
        # 'Proxy Authentication Required' error.
        return None

    def add_auth_header(self, request, header):
        """Add the authentication header to the request"""
        request.add_unredirected_header(self.auth_header, header)

    def auth_match(self, header, auth):
        """Check that we are able to handle that authentication scheme.

        The request authentication parameters may need to be
        updated with info from the server. Some of these
        parameters, when combined, are considered to be the
        authentication key, if one of them change the
        authentication result may change. 'user' and 'password'
        are exampls, but some auth schemes may have others
        (digest's nonce is an example, digest's nonce_count is a
        *counter-example*). Such parameters must be updated by
        using the update_auth() method.

        :param header: The authentication header sent by the server.
        :param auth: The auth parameters already known. They may be
             updated.
        :returns: True if we can try to handle the authentication.
        """
        raise NotImplementedError(self.auth_match)

    def build_auth_header(self, auth, request):
        """Build the value of the header used to authenticate.

        :param auth: The auth parameters needed to build the header.
        :param request: The request needing authentication.

        :return: None or header.
        """
        raise NotImplementedError(self.build_auth_header)

    def auth_successful(self, request, response):
        """The authentification was successful for the request.

        Additional infos may be available in the response.

        :param request: The succesfully authenticated request.
        :param response: The server response (may contain auth info).
        """
        # It may happen that we need to reconnect later, let's be ready
        self._retry_count = None

    def get_user_password(self, auth):
        """Ask user for a password if none is already available.

        :param auth: authentication info gathered so far (from the initial url
            and then during dialog with the server).
        """
        auth_conf = config.AuthenticationConfig()
        user = auth.get('user', None)
        password = auth.get('password', None)
        realm = auth['realm']
        port = auth.get('port', None)

        if user is None:
            user = auth_conf.get_user(auth['protocol'], auth['host'],
                                      port=port, path=auth['path'],
                                      realm=realm, ask=True,
                                      prompt=self.build_username_prompt(auth))
        if user is not None and password is None:
            password = auth_conf.get_password(
                auth['protocol'], auth['host'], user,
                port=port,
                path=auth['path'], realm=realm,
                prompt=self.build_password_prompt(auth))

        return user, password

    def _build_password_prompt(self, auth):
        """Build a prompt taking the protocol used into account.

        The AuthHandler is used by http and https, we want that information in
        the prompt, so we build the prompt from the authentication dict which
        contains all the needed parts.

        Also, http and proxy AuthHandlers present different prompts to the
        user. The daughter classes should implements a public
        build_password_prompt using this method.
        """
        prompt = u'%s' % auth['protocol'].upper() + u' %(user)s@%(host)s'
        realm = auth['realm']
        if realm is not None:
            prompt += u", Realm: '%s'" % realm
        prompt += u' password'
        return prompt

    def _build_username_prompt(self, auth):
        """Build a prompt taking the protocol used into account.

        The AuthHandler is used by http and https, we want that information in
        the prompt, so we build the prompt from the authentication dict which
        contains all the needed parts.

        Also, http and proxy AuthHandlers present different prompts to the
        user. The daughter classes should implements a public
        build_username_prompt using this method.
        """
        prompt = u'%s' % auth['protocol'].upper() + u' %(host)s'
        realm = auth['realm']
        if realm is not None:
            prompt += u", Realm: '%s'" % realm
        prompt += u' username'
        return prompt

    def http_request(self, request):
        """Insert an authentication header if information is available"""
        auth = self.get_auth(request)
        if self.auth_params_reusable(auth):
            self.add_auth_header(
                request, self.build_auth_header(auth, request))
        return request

    https_request = http_request  # FIXME: Need test


class NegotiateAuthHandler(AbstractAuthHandler):
    """A authentication handler that handles WWW-Authenticate: Negotiate.

    At the moment this handler supports just Kerberos. In the future,
    NTLM support may also be added.
    """

    scheme = 'negotiate'
    handler_order = 480
    requires_username = False

    def auth_match(self, header, auth):
        scheme, raw_auth = self._parse_auth_header(header)
        if scheme != self.scheme:
            return False
        self.update_auth(auth, 'scheme', scheme)
        resp = self._auth_match_kerberos(auth)
        if resp is None:
            return False
        # Optionally should try to authenticate using NTLM here
        self.update_auth(auth, 'negotiate_response', resp)
        return True

    def _auth_match_kerberos(self, auth):
        """Try to create a GSSAPI response for authenticating against a host."""
        global kerberos, checked_kerberos
        if kerberos is None and not checked_kerberos:
            try:
                import kerberos
            except ImportError:
                kerberos = None
            checked_kerberos = True
        if kerberos is None:
            return None
        ret, vc = kerberos.authGSSClientInit("HTTP@%(host)s" % auth)
        if ret < 1:
            trace.warning('Unable to create GSSAPI context for %s: %d',
                          auth['host'], ret)
            return None
        ret = kerberos.authGSSClientStep(vc, "")
        if ret < 0:
            trace.mutter('authGSSClientStep failed: %d', ret)
            return None
        return kerberos.authGSSClientResponse(vc)

    def build_auth_header(self, auth, request):
        return "Negotiate %s" % auth['negotiate_response']

    def auth_params_reusable(self, auth):
        # If the auth scheme is known, it means a previous
        # authentication was successful, all information is
        # available, no further checks are needed.
        return (auth.get('scheme', None) == 'negotiate' and
                auth.get('negotiate_response', None) is not None)


class BasicAuthHandler(AbstractAuthHandler):
    """A custom basic authentication handler."""

    scheme = 'basic'
    handler_order = 500
    auth_regexp = re.compile('realm="([^"]*)"', re.I)

    def build_auth_header(self, auth, request):
        raw = '%s:%s' % (auth['user'], auth['password'])
        auth_header = 'Basic ' + \
            base64.b64encode(raw.encode('utf-8')).decode('ascii')
        return auth_header

    def extract_realm(self, header_value):
        match = self.auth_regexp.search(header_value)
        realm = None
        if match:
            realm = match.group(1)
        return match, realm

    def auth_match(self, header, auth):
        scheme, raw_auth = self._parse_auth_header(header)
        if scheme != self.scheme:
            return False

        match, realm = self.extract_realm(raw_auth)
        if match:
            # Put useful info into auth
            self.update_auth(auth, 'scheme', scheme)
            self.update_auth(auth, 'realm', realm)
            if (auth.get('user', None) is None
                    or auth.get('password', None) is None):
                user, password = self.get_user_password(auth)
                self.update_auth(auth, 'user', user)
                self.update_auth(auth, 'password', password)
        return match is not None

    def auth_params_reusable(self, auth):
        # If the auth scheme is known, it means a previous
        # authentication was successful, all information is
        # available, no further checks are needed.
        return auth.get('scheme', None) == 'basic'


def get_digest_algorithm_impls(algorithm):
    H = None
    KD = None
    if algorithm == 'MD5':
        def H(x): return osutils.md5(x).hexdigest()
    elif algorithm == 'SHA':
        H = osutils.sha_string
    if H is not None:
        def KD(secret, data): return H(
            ("%s:%s" % (secret, data)).encode('utf-8'))
    return H, KD


def get_new_cnonce(nonce, nonce_count):
    raw = '%s:%d:%s:%s' % (nonce, nonce_count, time.ctime(),
                           osutils.rand_chars(8))
    return osutils.sha_string(raw.encode('utf-8'))[:16]


class DigestAuthHandler(AbstractAuthHandler):
    """A custom digest authentication handler."""

    scheme = 'digest'
    # Before basic as digest is a bit more secure and should be preferred
    handler_order = 490

    def auth_params_reusable(self, auth):
        # If the auth scheme is known, it means a previous
        # authentication was successful, all information is
        # available, no further checks are needed.
        return auth.get('scheme', None) == 'digest'

    def auth_match(self, header, auth):
        scheme, raw_auth = self._parse_auth_header(header)
        if scheme != self.scheme:
            return False

        # Put the requested authentication info into a dict
        req_auth = urllib_request.parse_keqv_list(
            urllib_request.parse_http_list(raw_auth))

        # Check that we can handle that authentication
        qop = req_auth.get('qop', None)
        if qop != 'auth':  # No auth-int so far
            return False

        H, KD = get_digest_algorithm_impls(req_auth.get('algorithm', 'MD5'))
        if H is None:
            return False

        realm = req_auth.get('realm', None)
        # Put useful info into auth
        self.update_auth(auth, 'scheme', scheme)
        self.update_auth(auth, 'realm', realm)
        if auth.get('user', None) is None or auth.get('password', None) is None:
            user, password = self.get_user_password(auth)
            self.update_auth(auth, 'user', user)
            self.update_auth(auth, 'password', password)

        try:
            if req_auth.get('algorithm', None) is not None:
                self.update_auth(auth, 'algorithm', req_auth.get('algorithm'))
            nonce = req_auth['nonce']
            if auth.get('nonce', None) != nonce:
                # A new nonce, never used
                self.update_auth(auth, 'nonce_count', 0)
            self.update_auth(auth, 'nonce', nonce)
            self.update_auth(auth, 'qop', qop)
            auth['opaque'] = req_auth.get('opaque', None)
        except KeyError:
            # Some required field is not there
            return False

        return True

    def build_auth_header(self, auth, request):
        if PY3:
            selector = request.selector
        else:
            selector = request.get_selector()
        url_scheme, url_selector = splittype(selector)
        sel_host, uri = splithost(url_selector)

        A1 = ('%s:%s:%s' %
              (auth['user'], auth['realm'], auth['password'])).encode('utf-8')
        A2 = ('%s:%s' % (request.get_method(), uri)).encode('utf-8')

        nonce = auth['nonce']
        qop = auth['qop']

        nonce_count = auth['nonce_count'] + 1
        ncvalue = '%08x' % nonce_count
        cnonce = get_new_cnonce(nonce, nonce_count)

        H, KD = get_digest_algorithm_impls(auth.get('algorithm', 'MD5'))
        nonce_data = '%s:%s:%s:%s:%s' % (nonce, ncvalue, cnonce, qop, H(A2))
        request_digest = KD(H(A1), nonce_data)

        header = 'Digest '
        header += 'username="%s", realm="%s", nonce="%s"' % (auth['user'],
                                                             auth['realm'],
                                                             nonce)
        header += ', uri="%s"' % uri
        header += ', cnonce="%s", nc=%s' % (cnonce, ncvalue)
        header += ', qop="%s"' % qop
        header += ', response="%s"' % request_digest
        # Append the optional fields
        opaque = auth.get('opaque', None)
        if opaque:
            header += ', opaque="%s"' % opaque
        if auth.get('algorithm', None):
            header += ', algorithm="%s"' % auth.get('algorithm')

        # We have used the nonce once more, update the count
        auth['nonce_count'] = nonce_count

        return header


class HTTPAuthHandler(AbstractAuthHandler):
    """Custom http authentication handler.

    Send the authentication preventively to avoid the roundtrip
    associated with the 401 error and keep the revelant info in
    the auth request attribute.
    """

    auth_required_header = 'www-authenticate'
    auth_header = 'Authorization'

    def get_auth(self, request):
        """Get the auth params from the request"""
        return request.auth

    def set_auth(self, request, auth):
        """Set the auth params for the request"""
        request.auth = auth

    def build_password_prompt(self, auth):
        return self._build_password_prompt(auth)

    def build_username_prompt(self, auth):
        return self._build_username_prompt(auth)

    def http_error_401(self, req, fp, code, msg, headers):
        return self.auth_required(req, headers)


class ProxyAuthHandler(AbstractAuthHandler):
    """Custom proxy authentication handler.

    Send the authentication preventively to avoid the roundtrip
    associated with the 407 error and keep the revelant info in
    the proxy_auth request attribute..
    """

    auth_required_header = 'proxy-authenticate'
    # FIXME: the correct capitalization is Proxy-Authorization,
    # but python-2.4 urllib_request.Request insist on using capitalize()
    # instead of title().
    auth_header = 'Proxy-authorization'

    def get_auth(self, request):
        """Get the auth params from the request"""
        return request.proxy_auth

    def set_auth(self, request, auth):
        """Set the auth params for the request"""
        request.proxy_auth = auth

    def build_password_prompt(self, auth):
        prompt = self._build_password_prompt(auth)
        prompt = u'Proxy ' + prompt
        return prompt

    def build_username_prompt(self, auth):
        prompt = self._build_username_prompt(auth)
        prompt = u'Proxy ' + prompt
        return prompt

    def http_error_407(self, req, fp, code, msg, headers):
        return self.auth_required(req, headers)


class HTTPBasicAuthHandler(BasicAuthHandler, HTTPAuthHandler):
    """Custom http basic authentication handler"""


class ProxyBasicAuthHandler(BasicAuthHandler, ProxyAuthHandler):
    """Custom proxy basic authentication handler"""


class HTTPDigestAuthHandler(DigestAuthHandler, HTTPAuthHandler):
    """Custom http basic authentication handler"""


class ProxyDigestAuthHandler(DigestAuthHandler, ProxyAuthHandler):
    """Custom proxy basic authentication handler"""


class HTTPNegotiateAuthHandler(NegotiateAuthHandler, HTTPAuthHandler):
    """Custom http negotiate authentication handler"""


class ProxyNegotiateAuthHandler(NegotiateAuthHandler, ProxyAuthHandler):
    """Custom proxy negotiate authentication handler"""


class HTTPErrorProcessor(urllib_request.HTTPErrorProcessor):
    """Process HTTP error responses.

    We don't really process the errors, quite the contrary
    instead, we leave our Transport handle them.
    """

    accepted_errors = [200,  # Ok
                       206,  # Partial content
                       404,  # Not found
                       ]
    """The error codes the caller will handle.

    This can be specialized in the request on a case-by case basis, but the
    common cases are covered here.
    """

    def http_response(self, request, response):
        code, msg, hdrs = response.code, response.msg, response.info()

        accepted_errors = request.accepted_errors
        if accepted_errors is None:
            accepted_errors = self.accepted_errors

        if code not in accepted_errors:
            response = self.parent.error('http', request, response,
                                         code, msg, hdrs)
        return response

    https_response = http_response


class HTTPDefaultErrorHandler(urllib_request.HTTPDefaultErrorHandler):
    """Translate common errors into Breezy Exceptions"""

    def http_error_default(self, req, fp, code, msg, hdrs):
        if code == 403:
            raise errors.TransportError(
                'Server refuses to fulfill the request (403 Forbidden)'
                ' for %s' % req.get_full_url())
        else:
            raise errors.InvalidHttpResponse(req.get_full_url(),
                                             'Unable to handle http code %d: %s'
                                             % (code, msg))


class Opener(object):
    """A wrapper around urllib_request.build_opener

    Daughter classes can override to build their own specific opener
    """
    # TODO: Provides hooks for daughter classes.

    def __init__(self,
                 connection=ConnectionHandler,
                 redirect=HTTPRedirectHandler,
                 error=HTTPErrorProcessor,
                 report_activity=None,
                 ca_certs=None):
        self._opener = urllib_request.build_opener(
            connection(report_activity=report_activity, ca_certs=ca_certs),
            redirect, error,
            ProxyHandler(),
            HTTPBasicAuthHandler(),
            HTTPDigestAuthHandler(),
            HTTPNegotiateAuthHandler(),
            ProxyBasicAuthHandler(),
            ProxyDigestAuthHandler(),
            ProxyNegotiateAuthHandler(),
            HTTPHandler,
            HTTPSHandler,
            HTTPDefaultErrorHandler,
            )

        self.open = self._opener.open
        if DEBUG >= 9:
            # When dealing with handler order, it's easy to mess
            # things up, the following will help understand which
            # handler is used, when and for what.
            import pprint
            pprint.pprint(self._opener.__dict__)
