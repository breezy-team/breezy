# Copyright (C) 2005-2010 Canonical Ltd
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

"""Base implementation of Transport over http using urllib.

There are separate implementation modules for each http client implementation.
"""

DEBUG = 0

import base64
import errno
import http.client
import os
import re
import socket
import ssl
import sys
import time
import urllib
import urllib.request
import weakref
from urllib.parse import urlencode, urljoin, urlparse

from ... import config, debug, errors, osutils, trace, transport, ui, urlutils
from ...bzr.smart import medium
from ...trace import mutter, mutter_callsite
from ...transport import ConnectedTransport, NoSuchFile, UnusableRedirect
from . import default_user_agent, ssl

# TODO: handle_response should be integrated into the http/__init__.py
from .response import handle_response

# FIXME: Oversimplifying, two kind of exceptions should be
# raised, once a request is issued: URLError before we have been
# able to process the response, HTTPError after that. Process the
# response means we are able to leave the socket clean, so if we
# are not able to do that, we should close the connection. The
# actual code more or less do that, tests should be written to
# ensure that.


checked_kerberos = False
kerberos = None


def splitport(host):
    m = re.fullmatch("(.*):([0-9]*)", host, re.DOTALL)
    if m:
        host, port = m.groups()
        return host, port or None
    return host, None


class _ReportingFileSocket:
    def __init__(self, filesock, report_activity=None):
        self.filesock = filesock
        self._report_activity = report_activity

    def report_activity(self, size, direction):
        if self._report_activity:
            self._report_activity(size, direction)

    def read(self, size=1):
        s = self.filesock.read(size)
        self.report_activity(len(s), "read")
        return s

    def readline(self, size=-1):
        s = self.filesock.readline(size)
        self.report_activity(len(s), "read")
        return s

    def readinto(self, b):
        s = self.filesock.readinto(b)
        self.report_activity(s, "read")
        return s

    def __getattr__(self, name):
        return getattr(self.filesock, name)


class _ReportingSocket:
    def __init__(self, sock, report_activity=None):
        self.sock = sock
        self._report_activity = report_activity

    def report_activity(self, size, direction):
        if self._report_activity:
            self._report_activity(size, direction)

    def sendall(self, s, *args):
        self.sock.sendall(s, *args)
        self.report_activity(len(s), "write")

    def recv(self, *args):
        s = self.sock.recv(*args)
        self.report_activity(len(s), "read")
        return s

    def makefile(self, mode="r", bufsize=-1):
        # http.client creates a fileobject that doesn't do buffering, which
        # makes fp.readline() very expensive because it only reads one byte
        # at a time.  So we wrap the socket in an object that forces
        # sock.makefile to make a buffered file.
        fsock = self.sock.makefile(mode, 65536)
        # And wrap that into a reporting kind of fileobject
        return _ReportingFileSocket(fsock, self._report_activity)

    def __getattr__(self, name):
        return getattr(self.sock, name)


# We define our own Response class to keep our http.client pipe clean
class Response(http.client.HTTPResponse):
    """Custom HTTPResponse, to avoid the need to decorate.

    http.client prefers to decorate the returned objects, rather
    than using a custom object.
    """

    # Some responses have bodies in which we have no interest
    _body_ignored_responses = [301, 302, 303, 307, 308, 404, 501]

    # in finish() below, we may have to discard several MB in the worst
    # case. To avoid buffering that much, we read and discard by chunks
    # instead. The underlying file is either a socket or a StringIO, so reading
    # 8k chunks should be fine.
    _discarded_buf_size = 8192

    def __init__(self, sock, debuglevel=0, method=None, url=None):
        self.url = url
        super().__init__(sock, debuglevel=debuglevel, method=method, url=url)

    def begin(self):
        """Begin to read the response from the server.

        http.client assumes that some responses get no content and do
        not even attempt to read the body in that case, leaving
        the body in the socket, blocking the next request. Let's
        try to workaround that.
        """
        http.client.HTTPResponse.begin(self)
        if self.status in self._body_ignored_responses:
            if self.debuglevel >= 2:
                print(
                    "For status: [{}], will ready body, length: {}".format(
                        self.status, self.length
                    )
                )
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
                    print("Consumed body: [{}]".format(body))
            self.close()
        elif self.status == 200:
            # Whatever the request is, it went ok, so we surely don't want to
            # close the connection. Some cases are not correctly detected by
            # http.client.HTTPConnection.getresponse (called by
            # http.client.HTTPResponse.begin). The CONNECT response for the https
            # through proxy case is one.  Note: the 'will_close' below refers
            # to the "true" socket between us and the server, whereas the
            # 'close()' above refers to the copy of that socket created by
            # http.client for the response itself. So, in the if above we close the
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


# Not inheriting from 'object' because http.client.HTTPConnection doesn't.
class AbstractHTTPConnection:
    """A custom HTTP(S) Connection, which can reset itself on a bad response."""

    response_class = Response

    # When we detect a server responding with the whole file to range requests,
    # we want to warn. But not below a given thresold.
    _range_warning_thresold = 1024 * 1024

    def __init__(self, report_activity=None):
        self._response = None
        self._report_activity = report_activity
        self._ranges_received_whole_file = None

    def _mutter_connect(self):
        netloc = "{}:{}".format(self.host, self.port)
        if self.proxied_host is not None:
            netloc += "(proxy for {})".format(self.proxied_host)
        trace.mutter("* About to connect() to {}".format(netloc))

    def getresponse(self):
        """Capture the response to be able to cleanup."""
        self._response = http.client.HTTPConnection.getresponse(self)
        return self._response

    def cleanup_pipe(self):
        """Read the remaining bytes of the last response if any."""
        if self._response is not None:
            try:
                pending = self._response.finish()
                # Warn the user (once)
                if (
                    self._ranges_received_whole_file is None
                    and self._response.status == 200
                    and pending
                    and pending > self._range_warning_thresold
                ):
                    self._ranges_received_whole_file = True
                    trace.warning(
                        "Got a 200 response when asking for multiple ranges,"
                        " does your server at %s:%s support range requests?",
                        self.host,
                        self.port,
                    )
            except OSError as e:
                # It's conceivable that the socket is in a bad state here
                # (including some test cases) and in this case, it doesn't need
                # cleaning anymore, so no need to fail, we just get rid of the
                # socket and let callers reconnect
                if len(e.args) == 0 or e.args[0] not in (
                    errno.ECONNRESET,
                    errno.ECONNABORTED,
                ):
                    raise
                self.close()
            self._response = None
        # Preserve our preciousss
        sock = self.sock
        self.sock = None
        # Let http.client.HTTPConnection do its housekeeping
        self.close()
        # Restore our preciousss
        self.sock = sock

    def _wrap_socket_for_reporting(self, sock):
        """Wrap the socket before anybody use it."""
        self.sock = _ReportingSocket(sock, self._report_activity)


class HTTPConnection(AbstractHTTPConnection, http.client.HTTPConnection):  # type: ignore
    # XXX: Needs refactoring at the caller level.
    def __init__(
        self, host, port=None, proxied_host=None, report_activity=None, ca_certs=None
    ):
        AbstractHTTPConnection.__init__(self, report_activity=report_activity)
        http.client.HTTPConnection.__init__(self, host, port)
        self.proxied_host = proxied_host
        # ca_certs is ignored, it's only relevant for https

    def connect(self):
        if "http" in debug.debug_flags:
            self._mutter_connect()
        http.client.HTTPConnection.connect(self)
        self._wrap_socket_for_reporting(self.sock)


class HTTPSConnection(AbstractHTTPConnection, http.client.HTTPSConnection):  # type: ignore
    def __init__(
        self,
        host,
        port=None,
        key_file=None,
        cert_file=None,
        proxied_host=None,
        report_activity=None,
        ca_certs=None,
    ):
        AbstractHTTPConnection.__init__(self, report_activity=report_activity)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if key_file or cert_file:
            context.load_cert_chain(cert_file, key_file)
        self.cert_file = cert_file
        self.key_file = key_file
        http.client.HTTPSConnection.__init__(self, host, port, context=context)
        self.proxied_host = proxied_host
        self.ca_certs = ca_certs

    def connect(self):
        if "http" in debug.debug_flags:
            self._mutter_connect()
        http.client.HTTPConnection.connect(self)
        self._wrap_socket_for_reporting(self.sock)
        if self.proxied_host is None:
            self.connect_to_origin()

    def connect_to_origin(self):
        # FIXME JRV 2011-12-18: Use location config here?
        config_stack = config.GlobalStack()
        cert_reqs = config_stack.get("ssl.cert_reqs")
        if self.proxied_host is not None:
            host = self.proxied_host.split(":", 1)[0]
        else:
            host = self.host
        if cert_reqs == ssl.CERT_NONE:
            ui.ui_factory.show_user_warning("not_checking_ssl_cert", host=host)
            ui.ui_factory.suppressed_warnings.add("not_checking_ssl_cert")
            ca_certs = None
        else:
            if self.ca_certs is None:
                ca_certs = config_stack.get("ssl.ca_certs")
            else:
                ca_certs = self.ca_certs
            if ca_certs is None:
                trace.warning(
                    "No valid trusted SSL CA certificates file set. See "
                    "'brz help ssl.ca_certs' for more information on setting "
                    "trusted CAs."
                )
        try:
            ssl_context = ssl.create_default_context(
                purpose=ssl.Purpose.SERVER_AUTH, cafile=ca_certs
            )
            ssl_context.check_hostname = cert_reqs != ssl.CERT_NONE
            if self.cert_file:
                ssl_context.load_cert_chain(
                    keyfile=self.key_file, certfile=self.cert_file
                )
            ssl_context.verify_mode = cert_reqs
            ssl_sock = ssl_context.wrap_socket(self.sock, server_hostname=self.host)
        except ssl.SSLError:
            trace.note(
                "\n"
                "See `brz help ssl.ca_certs` for how to specify trusted CA"
                "certificates.\n"
                "Pass -Ossl.cert_reqs=none to disable certificate "
                "verification entirely.\n"
            )
            raise
        # Wrap the ssl socket before anybody use it
        self._wrap_socket_for_reporting(ssl_sock)


class Request(urllib.request.Request):
    """A custom Request object.

    urllib.request determines the request method heuristically (based on
    the presence or absence of data). We set the method
    statically.

    The Request object tracks:
    - the connection the request will be made on.
    - the authentication parameters needed to preventively set
      the authentication header once a first authentication have
       been made.
    """

    def __init__(
        self,
        method,
        url,
        data=None,
        headers=None,
        origin_req_host=None,
        unverifiable=False,
        connection=None,
        parent=None,
    ):
        if headers is None:
            headers = {}
        urllib.request.Request.__init__(
            self, url, data, headers, origin_req_host, unverifiable
        )
        self.method = method
        self.connection = connection
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
        host, port = splitport(self.host)
        if port is None:
            # We need to set the default port ourselves way before it gets set
            # in the HTTP[S]Connection object at build time.
            if self.type == "https":
                conn_class = HTTPSConnection
            else:
                conn_class = HTTPConnection
            port = conn_class.default_port
        self.proxied_host = "{}:{}".format(host, port)
        urllib.request.Request.set_proxy(self, proxy, type)
        # When urllib.request makes a https request with our wrapper code and a proxy,
        # it sets Host to the https proxy, not the host we want to talk to.
        # I'm fairly sure this is our fault, but what is the cause is an open
        # question. -- Robert Collins May 8 2010.
        self.add_unredirected_header("Host", self.proxied_host)


class _ConnectRequest(Request):
    def __init__(self, request):
        """Constructor.

        :param request: the first request sent to the proxied host, already
            processed by the opener (i.e. proxied_host is already set).
        """
        # We give a fake url and redefine selector or urllib.request will be
        # confused
        Request.__init__(
            self, "CONNECT", request.get_full_url(), connection=request.connection
        )
        if request.proxied_host is None:
            raise AssertionError()
        self.proxied_host = request.proxied_host

    def get_selector(self):
        return self.proxied_host

    def set_selector(self, selector):
        self.proxied_host = selector

    selector = property(get_selector, set_selector)  # type: ignore

    def set_proxy(self, proxy, type):
        """Set the proxy without remembering the proxied host.

        We already know the proxied host by definition, the CONNECT request
        occurs only when the connection goes through a proxy. The usual
        processing (masquerade the request so that the connection is done to
        the proxy while the request is targeted at another host) does not apply
        here. In fact, the connection is already established with proxy and we
        just want to enable the SSL tunneling.
        """
        urllib.request.Request.set_proxy(self, proxy, type)


class ConnectionHandler(urllib.request.BaseHandler):
    """Provides connection-sharing by pre-processing requests.

    urllib.request provides no way to access the HTTPConnection object
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
            raise urlutils.InvalidURL(request.get_full_url(), "no host given.")

        # We create a connection (but it will not connect until the first
        # request is made)
        try:
            connection = http_connection_class(
                host,
                proxied_host=request.proxied_host,
                report_activity=self._report_activity,
                ca_certs=self.ca_certs,
            )
        except http.client.InvalidURL:
            # There is only one occurrence of InvalidURL in http.client
            raise urlutils.InvalidURL(request.get_full_url(), extra="nonnumeric port")

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


class AbstractHTTPHandler(urllib.request.AbstractHTTPHandler):
    """A custom handler for HTTP(S) requests.

    We overrive urllib.request.AbstractHTTPHandler to get a better
    control of the connection, the ability to implement new
    request types and return a response able to cope with
    persistent connections.
    """

    # We change our order to be before urllib.request HTTP[S]Handlers
    # and be chosen instead of them (the first http_open called
    # wins).
    handler_order = 400

    _default_headers = {
        "Pragma": "no-cache",
        "Cache-control": "max-age=0",
        "Connection": "Keep-Alive",
        "User-agent": default_user_agent(),
        "Accept": "*/*",
    }

    def __init__(self):
        urllib.request.AbstractHTTPHandler.__init__(self, debuglevel=DEBUG)

    def http_request(self, request):
        """Common headers setting."""
        for name, value in self._default_headers.items():
            if name not in request.headers:
                request.headers[name] = value
        # FIXME: We may have to add the Content-Length header if
        # we have data to send.
        return request

    def retry_or_raise(self, http_class, request, first_try):
        """Retry the request (once) or raise the exception.

        urllib.request raises exception of application level kind, we
        just have to translate them.

        http.client can raise exceptions of transport level (badly
        formatted dialog, loss of connexion or socket level
        problems). In that case we should issue the request again
        (http.client will close and reopen a new connection if
        needed).
        """
        # When an exception occurs, we give back the original
        # Traceback or the bugs are hard to diagnose.
        exc_type, exc_val, exc_tb = sys.exc_info()
        if exc_type == socket.gaierror:
            # No need to retry, that will not help
            origin_req_host = request.origin_req_host
            raise errors.ConnectionError(
                "Couldn't resolve host '{}'".format(origin_req_host), orig_error=exc_val
            )
        elif isinstance(exc_val, http.client.ImproperConnectionState):
            # The http.client pipeline is in incorrect state, it's a bug in our
            # implementation.
            raise exc_val.with_traceback(exc_tb)
        else:
            if first_try:
                if self._debuglevel >= 2:
                    print("Received exception: [{!r}]".format(exc_val))
                    print("  On connection: [{!r}]".format(request.connection))
                    method = request.get_method()
                    url = request.get_full_url()
                    print("  Will retry, {} {!r}".format(method, url))
                request.connection.close()
                response = self.do_open(http_class, request, False)
            else:
                if self._debuglevel >= 2:
                    print("Received second exception: [{!r}]".format(exc_val))
                    print("  On connection: [{!r}]".format(request.connection))
                if exc_type in (http.client.BadStatusLine, http.client.UnknownProtocol):
                    # http.client.BadStatusLine and
                    # http.client.UnknownProtocol indicates that a
                    # bogus server was encountered or a bad
                    # connection (i.e. transient errors) is
                    # experimented, we have already retried once
                    # for that request so we raise the exception.
                    my_exception = errors.InvalidHttpResponse(
                        request.get_full_url(),
                        "Bad status line received",
                        orig_error=exc_val,
                    )
                elif (
                    isinstance(exc_val, socket.error)
                    and len(exc_val.args)
                    and exc_val.args[0] in (errno.ECONNRESET, 10053, 10054)
                ):
                    # 10053 == WSAECONNABORTED
                    # 10054 == WSAECONNRESET
                    raise errors.ConnectionReset(
                        "Connection lost while sending request."
                    )
                else:
                    # All other exception are considered connection related.

                    # socket errors generally occurs for reasons
                    # far outside our scope, so closing the
                    # connection and retrying is the best we can
                    # do.
                    selector = request.selector
                    my_exception = errors.ConnectionError(
                        msg="while sending {} {}:".format(
                            request.get_method(), selector
                        ),
                        orig_error=exc_val,
                    )

                if self._debuglevel >= 2:
                    print("On connection: [{!r}]".format(request.connection))
                    method = request.get_method()
                    url = request.get_full_url()
                    print("  Failed again, {} {!r}".format(method, url))
                    print("  Will raise: [{!r}]".format(my_exception))
                raise my_exception.with_traceback(exc_tb)
        return response

    def do_open(self, http_class, request, first_try=True):
        """See urllib.request.AbstractHTTPHandler.do_open for the general idea.

        The request will be retried once if it fails.
        """
        connection = request.connection
        if connection is None:
            raise AssertionError("Cannot process a request without a connection")

        # Get all the headers
        headers = {}
        headers.update(request.header_items())
        headers.update(request.unredirected_hdrs)
        # Some servers or proxies will choke on headers not properly
        # cased. http.client/urllib/urllib.request all use capitalize to get canonical
        # header names, but only python2.5 urllib.request use title() to fix them just
        # before sending the request. And not all versions of python 2.5 do
        # that. Since we replace urllib.request.AbstractHTTPHandler.do_open we do it
        # ourself below.
        headers = {name.title(): val for name, val in headers.items()}

        try:
            method = request.get_method()
            url = request.selector
            connection._send_request(
                method,
                url,
                # FIXME: implements 100-continue
                # None, # We don't send the body yet
                request.data,
                headers,
                encode_chunked=(headers.get("Transfer-Encoding") == "chunked"),
            )
            if "http" in debug.debug_flags:
                trace.mutter("> {} {}".format(method, url))
                hdrs = []
                for k, v in headers.items():
                    # People are often told to paste -Dhttp output to help
                    # debug. Don't compromise credentials.
                    if k in ("Authorization", "Proxy-Authorization"):
                        v = "<masked>"
                    hdrs.append("{}: {}".format(k, v))
                trace.mutter("> " + "\n> ".join(hdrs) + "\n")
            if self._debuglevel >= 1:
                print(
                    "Request sent: [{!r}] from ({})".format(
                        request, request.connection.sock.getsockname()
                    )
                )
            response = connection.getresponse()
            convert_to_addinfourl = True
        except (ssl.SSLError, ssl.CertificateError):
            # Something is wrong with either the certificate or the hostname,
            # re-trying won't help
            raise
        except (
            socket.gaierror,
            http.client.BadStatusLine,
            http.client.UnknownProtocol,
            OSError,
            http.client.HTTPException,
        ):
            response = self.retry_or_raise(http_class, request, first_try)
            convert_to_addinfourl = False

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
            print("Receives response: {!r}".format(response))
            print(
                "  For: {!r}({!r})".format(request.get_method(), request.get_full_url())
            )

        if convert_to_addinfourl:
            # Shamelessly copied from urllib.request
            req = request
            r = response
            r.recv = r.read
            fp = socket._fileobject(r, bufsize=65536)
            resp = urllib.request.addinfourl(fp, r.msg, req.get_full_url())
            resp.code = r.status
            resp.msg = r.reason
            resp.version = r.version
            if self._debuglevel >= 2:
                print("Create addinfourl: {!r}".format(resp))
                print(
                    "  For: {!r}({!r})".format(
                        request.get_method(), request.get_full_url()
                    )
                )
            if "http" in debug.debug_flags:
                version = "HTTP/%d.%d"
                try:
                    version = version % (resp.version / 10, resp.version % 10)
                except:
                    version = "HTTP/{!r}".format(resp.version)
                trace.mutter("< {} {} {}".format(version, resp.code, resp.msg))
                # Use the raw header lines instead of treating resp.info() as a
                # dict since we may miss duplicated headers otherwise.
                hdrs = [h.rstrip("\r\n") for h in resp.info().headers]
                trace.mutter("< " + "\n< ".join(hdrs) + "\n")
        else:
            resp = response
        return resp


class HTTPHandler(AbstractHTTPHandler):
    """A custom handler that just thunks into HTTPConnection."""

    def http_open(self, request):
        return self.do_open(HTTPConnection, request)


class HTTPSHandler(AbstractHTTPHandler):
    """A custom handler that just thunks into HTTPSConnection."""

    https_request = AbstractHTTPHandler.http_request

    def https_open(self, request):
        connection = request.connection
        if (
            connection.sock is None
            and connection.proxied_host is not None
            and request.get_method() != "CONNECT"
        ):  # Don't loop
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
                raise errors.ConnectionError(
                    "Can't connect to {} via proxy {}".format(
                        connect.proxied_host, self.host
                    )
                )
            # Housekeeping
            connection.cleanup_pipe()
            # Establish the connection encryption
            connection.connect_to_origin()
            # Propagate the connection to the original request
            request.connection = connection
        return self.do_open(HTTPSConnection, request)


class HTTPRedirectHandler(urllib.request.HTTPRedirectHandler):
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
        """See urllib.request.HTTPRedirectHandler.redirect_request."""
        # We would have preferred to update the request instead
        # of creating a new one, but the urllib.request.Request object
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

        origin_req_host = req.origin_req_host

        if code in (301, 302, 303, 307, 308):
            return Request(
                req.get_method(),
                newurl,
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
            raise urllib.request.HTTPError(req.get_full_url(), code, msg, headers, fp)

    def http_error_302(self, req, fp, code, msg, headers):
        """Requests the redirected to URI.

        Copied from urllib.request to be able to clean the pipe of the associated
        connection, *before* issuing the redirected request but *after* having
        eventually raised an error.
        """
        # Some servers (incorrectly) return multiple Location headers
        # (so probably same goes for URI).  Use first header.

        # TODO: Once we get rid of addinfourl objects, the
        # following will need to be updated to use correct case
        # for headers.
        if "location" in headers:
            newurl = headers.get("location")
        elif "uri" in headers:
            newurl = headers.get("uri")
        else:
            return

        newurl = urljoin(req.get_full_url(), newurl)

        if self._debuglevel >= 1:
            print(
                "Redirected to: {} (followed: {!r})".format(
                    newurl, req.follow_redirections
                )
            )
        if req.follow_redirections is False:
            req.redirected_to = newurl
            return fp

        # This call succeeds or raise an error. urllib.request returns
        # if redirect_request returns None, but our
        # redirect_request never returns None.
        redirected_req = self.redirect_request(req, fp, code, msg, headers, newurl)

        # loop detection
        # .redirect_dict has a key url if url was previously visited.
        if hasattr(req, "redirect_dict"):
            visited = redirected_req.redirect_dict = req.redirect_dict
            if (
                visited.get(newurl, 0) >= self.max_repeats
                or len(visited) >= self.max_redirections
            ):
                raise urllib.request.HTTPError(
                    req.get_full_url(), code, self.inf_msg + msg, headers, fp
                )
        else:
            visited = redirected_req.redirect_dict = req.redirect_dict = {}
        visited[newurl] = visited.get(newurl, 0) + 1

        # We can close the fp now that we are sure that we won't
        # use it with HTTPError.
        fp.close()
        # We have all we need already in the response
        req.connection.cleanup_pipe()

        return self.parent.open(redirected_req)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


class ProxyHandler(urllib.request.ProxyHandler):
    """Handles proxy setting.

    Copied and modified from urllib.request to be able to modify the request during
    the request pre-processing instead of modifying it at _open time. As we
    capture (or create) the connection object during request processing, _open
    time was too late.

    The main task is to modify the request so that the connection is done to
    the proxy while the request still refers to the destination host.

    Note: the proxy handling *may* modify the protocol used; the request may be
    against an https server proxied through an http proxy. So, https_request
    will be called, but later it's really http_open that will be called. This
    explains why we don't have to call self.parent.open as the urllib.request did.
    """

    # Proxies must be in front
    handler_order = 100
    _debuglevel = DEBUG

    def __init__(self, proxies=None):
        urllib.request.ProxyHandler.__init__(self, proxies)
        # First, let's get rid of urllib.request implementation
        for type, proxy in self.proxies.items():
            if self._debuglevel >= 3:
                print("Will unbind {}_open for {!r}".format(type, proxy))
            delattr(self, "{}_open".format(type))

        def bind_scheme_request(proxy, scheme):
            if proxy is None:
                return
            scheme_request = scheme + "_request"
            if self._debuglevel >= 3:
                print("Will bind {} for {!r}".format(scheme_request, proxy))
            setattr(
                self, scheme_request, lambda request: self.set_proxy(request, scheme)
            )

        # We are interested only by the http[s] proxies
        http_proxy = self.get_proxy_env_var("http")
        bind_scheme_request(http_proxy, "http")
        https_proxy = self.get_proxy_env_var("https")
        bind_scheme_request(https_proxy, "https")

    def get_proxy_env_var(self, name, default_to="all"):
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
        no_proxy = self.get_proxy_env_var("no", default_to=None)
        bypass = self.evaluate_proxy_bypass(host, no_proxy)
        if bypass is None:
            # Nevertheless, there are platform-specific ways to
            # ignore proxies...
            return urllib.request.proxy_bypass(host)
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
        for domain in no_proxy.split(","):
            domain = domain.strip()
            if domain == "":
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
        host = request.host
        if self.proxy_bypass(host):
            return request

        proxy = self.get_proxy_env_var(type)
        if self._debuglevel >= 3:
            print("set_proxy {}_request for {!r}".format(type, proxy))
        # FIXME: python 2.5 urlparse provides a better _parse_proxy which can
        # grok user:password@host:port as well as
        # http://user:password@host:port

        parsed_url = transport.ConnectedTransport._split_url(proxy)
        if not parsed_url.host:
            raise urlutils.InvalidURL(proxy, "No host component")

        if request.proxy_auth == {}:
            # No proxy auth parameter are available, we are handling the first
            # proxied request, intialize.  scheme (the authentication scheme)
            # and realm will be set by the AuthHandler
            request.proxy_auth = {
                "host": parsed_url.host,
                "port": parsed_url.port,
                "user": parsed_url.user,
                "password": parsed_url.password,
                "protocol": parsed_url.scheme,
                # We ignore path since we connect to a proxy
                "path": None,
            }
        if parsed_url.port is None:
            phost = parsed_url.host
        else:
            phost = parsed_url.host + ":%d" % parsed_url.port
        request.set_proxy(phost, type)
        if self._debuglevel >= 3:
            print("set_proxy: proxy set to {}://{}".format(type, phost))
        return request


class AbstractAuthHandler(urllib.request.BaseHandler):
    """A custom abstract authentication handler for all http authentications.

    Provides the meat to handle authentication errors and
    preventively set authentication headers after the first
    successful authentication.

    This can be used for http and proxy, as well as for basic, negotiate and
    digest authentications.

    This provides an unified interface for all authentication handlers
    (urllib.request provides far too many with different policies).

    The interaction between this handler and the urllib.request
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

    scheme: str
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
        """Update a value in auth marking the auth as modified if needed."""
        old_value = auth.get(key, None)
        if old_value != value:
            auth[key] = value
            auth["modified"] = True

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
        server_headers = headers.get_all(self.auth_required_header)
        if not server_headers:
            # The http error MUST have the associated
            # header. This must never happen in production code.
            trace.mutter("%s not found", self.auth_required_header)
            return None

        auth = self.get_auth(request)
        auth["modified"] = False
        # Put some common info in auth if the caller didn't
        if auth.get("path", None) is None:
            parsed_url = urlutils.URL.from_string(request.get_full_url())
            self.update_auth(auth, "protocol", parsed_url.scheme)
            self.update_auth(auth, "host", parsed_url.host)
            self.update_auth(auth, "port", parsed_url.port)
            self.update_auth(auth, "path", parsed_url.path)
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
                if (
                    request.get_header(self.auth_header, None) is not None
                    and not auth["modified"]
                ):
                    # We already tried that, give up
                    return None

                # Only the most secure scheme proposed by the server should be
                # used, since the handlers use 'handler_order' to describe that
                # property, the first handler tried takes precedence, the
                # others should not attempt to authenticate if the best one
                # failed.
                best_scheme = auth.get("best_scheme", None)
                if best_scheme is None:
                    # At that point, if current handler should doesn't succeed
                    # the credentials are wrong (or incomplete), but we know
                    # that the associated scheme should be used.
                    best_scheme = auth["best_scheme"] = self.scheme
                if best_scheme != self.scheme:
                    continue

                if self.requires_username and auth.get("user", None) is None:
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
        """Add the authentication header to the request."""
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
        user = auth.get("user", None)
        password = auth.get("password", None)
        realm = auth["realm"]
        port = auth.get("port", None)

        if user is None:
            user = auth_conf.get_user(
                auth["protocol"],
                auth["host"],
                port=port,
                path=auth["path"],
                realm=realm,
                ask=True,
                prompt=self.build_username_prompt(auth),
            )
        if user is not None and password is None:
            password = auth_conf.get_password(
                auth["protocol"],
                auth["host"],
                user,
                port=port,
                path=auth["path"],
                realm=realm,
                prompt=self.build_password_prompt(auth),
            )

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
        prompt = "{}".format(auth["protocol"].upper()) + " %(user)s@%(host)s"
        realm = auth["realm"]
        if realm is not None:
            prompt += ", Realm: '{}'".format(realm)
        prompt += " password"
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
        prompt = "{}".format(auth["protocol"].upper()) + " %(host)s"
        realm = auth["realm"]
        if realm is not None:
            prompt += ", Realm: '{}'".format(realm)
        prompt += " username"
        return prompt

    def http_request(self, request):
        """Insert an authentication header if information is available."""
        auth = self.get_auth(request)
        if self.auth_params_reusable(auth):
            self.add_auth_header(request, self.build_auth_header(auth, request))
        return request

    https_request = http_request  # FIXME: Need test


class NegotiateAuthHandler(AbstractAuthHandler):
    """A authentication handler that handles WWW-Authenticate: Negotiate.

    At the moment this handler supports just Kerberos. In the future,
    NTLM support may also be added.
    """

    scheme = "negotiate"
    handler_order = 480
    requires_username = False

    def auth_match(self, header, auth):
        scheme, _raw_auth = self._parse_auth_header(header)
        if scheme != self.scheme:
            return False
        self.update_auth(auth, "scheme", scheme)
        resp = self._auth_match_kerberos(auth)
        if resp is None:
            return False
        # Optionally should try to authenticate using NTLM here
        self.update_auth(auth, "negotiate_response", resp)
        return True

    def _auth_match_kerberos(self, auth):
        """Try to create a GSSAPI response for authenticating against a host."""
        global kerberos, checked_kerberos
        if kerberos is None and not checked_kerberos:
            try:
                import kerberos
            except ModuleNotFoundError:
                kerberos = None
            checked_kerberos = True
        if kerberos is None:
            return None
        ret, vc = kerberos.authGSSClientInit("HTTP@{host}".format(**auth))
        if ret < 1:
            trace.warning(
                "Unable to create GSSAPI context for %s: %d", auth["host"], ret
            )
            return None
        ret = kerberos.authGSSClientStep(vc, "")
        if ret < 0:
            trace.mutter("authGSSClientStep failed: %d", ret)
            return None
        return kerberos.authGSSClientResponse(vc)

    def build_auth_header(self, auth, request):
        return "Negotiate {}".format(auth["negotiate_response"])

    def auth_params_reusable(self, auth):
        # If the auth scheme is known, it means a previous
        # authentication was successful, all information is
        # available, no further checks are needed.
        return (
            auth.get("scheme", None) == "negotiate"
            and auth.get("negotiate_response", None) is not None
        )


class BasicAuthHandler(AbstractAuthHandler):
    """A custom basic authentication handler."""

    scheme = "basic"
    handler_order = 500
    auth_regexp = re.compile('realm="([^"]*)"', re.I)

    def build_auth_header(self, auth, request):
        raw = "{}:{}".format(auth["user"], auth["password"])
        auth_header = "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii")
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
            self.update_auth(auth, "scheme", scheme)
            self.update_auth(auth, "realm", realm)
            if auth.get("user", None) is None or auth.get("password", None) is None:
                user, password = self.get_user_password(auth)
                self.update_auth(auth, "user", user)
                self.update_auth(auth, "password", password)
        return match is not None

    def auth_params_reusable(self, auth):
        # If the auth scheme is known, it means a previous
        # authentication was successful, all information is
        # available, no further checks are needed.
        return auth.get("scheme", None) == "basic"


def get_digest_algorithm_impls(algorithm):
    H = None
    KD = None
    if algorithm == "MD5":

        def H(x):
            return osutils.md5(x).hexdigest()
    elif algorithm == "SHA":
        H = osutils.sha_string
    if H is not None:

        def KD(secret, data):
            return H(("{}:{}".format(secret, data)).encode("utf-8"))

    return H, KD


def get_new_cnonce(nonce, nonce_count):
    raw = "%s:%d:%s:%s" % (nonce, nonce_count, time.ctime(), osutils.rand_chars(8))
    return osutils.sha_string(raw.encode("utf-8"))[:16]


class DigestAuthHandler(AbstractAuthHandler):
    """A custom digest authentication handler."""

    scheme = "digest"
    # Before basic as digest is a bit more secure and should be preferred
    handler_order = 490

    def auth_params_reusable(self, auth):
        # If the auth scheme is known, it means a previous
        # authentication was successful, all information is
        # available, no further checks are needed.
        return auth.get("scheme", None) == "digest"

    def auth_match(self, header, auth):
        scheme, raw_auth = self._parse_auth_header(header)
        if scheme != self.scheme:
            return False

        # Put the requested authentication info into a dict
        req_auth = urllib.request.parse_keqv_list(
            urllib.request.parse_http_list(raw_auth)
        )

        # Check that we can handle that authentication
        qop = req_auth.get("qop", None)
        if qop != "auth":  # No auth-int so far
            return False

        H, _KD = get_digest_algorithm_impls(req_auth.get("algorithm", "MD5"))
        if H is None:
            return False

        realm = req_auth.get("realm", None)
        # Put useful info into auth
        self.update_auth(auth, "scheme", scheme)
        self.update_auth(auth, "realm", realm)
        if auth.get("user", None) is None or auth.get("password", None) is None:
            user, password = self.get_user_password(auth)
            self.update_auth(auth, "user", user)
            self.update_auth(auth, "password", password)

        try:
            if req_auth.get("algorithm", None) is not None:
                self.update_auth(auth, "algorithm", req_auth.get("algorithm"))
            nonce = req_auth["nonce"]
            if auth.get("nonce", None) != nonce:
                # A new nonce, never used
                self.update_auth(auth, "nonce_count", 0)
            self.update_auth(auth, "nonce", nonce)
            self.update_auth(auth, "qop", qop)
            auth["opaque"] = req_auth.get("opaque", None)
        except KeyError:
            # Some required field is not there
            return False

        return True

    def build_auth_header(self, auth, request):
        uri = urlparse(request.selector).path

        A1 = ("{}:{}:{}".format(auth["user"], auth["realm"], auth["password"])).encode(
            "utf-8"
        )
        A2 = ("{}:{}".format(request.get_method(), uri)).encode("utf-8")

        nonce = auth["nonce"]
        qop = auth["qop"]

        nonce_count = auth["nonce_count"] + 1
        ncvalue = "{:08x}".format(nonce_count)
        cnonce = get_new_cnonce(nonce, nonce_count)

        H, KD = get_digest_algorithm_impls(auth.get("algorithm", "MD5"))
        nonce_data = "{}:{}:{}:{}:{}".format(nonce, ncvalue, cnonce, qop, H(A2))
        request_digest = KD(H(A1), nonce_data)

        header = "Digest "
        header += 'username="{}", realm="{}", nonce="{}"'.format(
            auth["user"], auth["realm"], nonce
        )
        header += ', uri="{}"'.format(uri)
        header += ', cnonce="{}", nc={}'.format(cnonce, ncvalue)
        header += ', qop="{}"'.format(qop)
        header += ', response="{}"'.format(request_digest)
        # Append the optional fields
        opaque = auth.get("opaque", None)
        if opaque:
            header += ', opaque="{}"'.format(opaque)
        if auth.get("algorithm", None):
            header += ', algorithm="{}"'.format(auth.get("algorithm"))

        # We have used the nonce once more, update the count
        auth["nonce_count"] = nonce_count

        return header


class HTTPAuthHandler(AbstractAuthHandler):
    """Custom http authentication handler.

    Send the authentication preventively to avoid the roundtrip
    associated with the 401 error and keep the revelant info in
    the auth request attribute.
    """

    auth_required_header = "www-authenticate"
    auth_header = "Authorization"

    def get_auth(self, request):
        """Get the auth params from the request."""
        return request.auth

    def set_auth(self, request, auth):
        """Set the auth params for the request."""
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

    auth_required_header = "proxy-authenticate"
    # FIXME: the correct capitalization is Proxy-Authorization,
    # but python-2.4 urllib.request.Request insist on using capitalize()
    # instead of title().
    auth_header = "Proxy-authorization"

    def get_auth(self, request):
        """Get the auth params from the request."""
        return request.proxy_auth

    def set_auth(self, request, auth):
        """Set the auth params for the request."""
        request.proxy_auth = auth

    def build_password_prompt(self, auth):
        prompt = self._build_password_prompt(auth)
        prompt = "Proxy " + prompt
        return prompt

    def build_username_prompt(self, auth):
        prompt = self._build_username_prompt(auth)
        prompt = "Proxy " + prompt
        return prompt

    def http_error_407(self, req, fp, code, msg, headers):
        return self.auth_required(req, headers)


class HTTPBasicAuthHandler(BasicAuthHandler, HTTPAuthHandler):
    """Custom http basic authentication handler."""


class ProxyBasicAuthHandler(BasicAuthHandler, ProxyAuthHandler):
    """Custom proxy basic authentication handler."""


class HTTPDigestAuthHandler(DigestAuthHandler, HTTPAuthHandler):
    """Custom http basic authentication handler."""


class ProxyDigestAuthHandler(DigestAuthHandler, ProxyAuthHandler):
    """Custom proxy basic authentication handler."""


class HTTPNegotiateAuthHandler(NegotiateAuthHandler, HTTPAuthHandler):
    """Custom http negotiate authentication handler."""


class ProxyNegotiateAuthHandler(NegotiateAuthHandler, ProxyAuthHandler):
    """Custom proxy negotiate authentication handler."""


class HTTPErrorProcessor(urllib.request.HTTPErrorProcessor):
    """Process HTTP error responses.

    We don't really process the errors, quite the contrary
    instead, we leave our Transport handle them.
    """

    accepted_errors = [
        200,  # Ok
        201,
        202,
        204,
        206,  # Partial content
        207,  # Multi-Status Response (for webdav)
        400,
        403,
        404,  # Not found
        405,  # Method not allowed
        406,  # Not Acceptable
        409,  # Conflict
        412,  # Precondition failed (for webdav)
        416,  # Range not satisfiable
        422,  # Unprocessible entity
        501,  # Not implemented
    ]
    """The error codes the caller will handle.

    This can be specialized in the request on a case-by case basis, but the
    common cases are covered here.
    """

    def http_response(self, request, response):
        code, msg, hdrs = response.code, response.msg, response.info()

        if code not in self.accepted_errors:
            response = self.parent.error("http", request, response, code, msg, hdrs)
        return response

    https_response = http_response


class HTTPDefaultErrorHandler(urllib.request.HTTPDefaultErrorHandler):
    """Translate common errors into Breezy Exceptions."""

    def http_error_default(self, req, fp, code, msg, hdrs):
        if code == 403:
            raise errors.TransportError(
                "Server refuses to fulfill the request (403 Forbidden) for {}".format(
                    req.get_full_url()
                )
            )
        else:
            raise errors.UnexpectedHttpStatus(
                req.get_full_url(),
                code,
                "Unable to handle http code: {}".format(msg),
                headers=hdrs,
            )


class Opener:
    """A wrapper around urllib.request.build_opener.

    Daughter classes can override to build their own specific opener
    """

    # TODO: Provides hooks for daughter classes.

    def __init__(
        self,
        connection=ConnectionHandler,
        redirect=HTTPRedirectHandler,
        error=HTTPErrorProcessor,
        report_activity=None,
        ca_certs=None,
    ):
        self._opener = urllib.request.build_opener(
            connection(report_activity=report_activity, ca_certs=ca_certs),
            redirect,
            error,
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


class HttpTransport(ConnectedTransport):
    """HTTP Client implementations.

    The protocol can be given as e.g. http+urllib://host/ to use a particular
    implementation.
    """

    # _unqualified_scheme: "http" or "https"
    # _scheme: may have "+pycurl", etc

    # In order to debug we have to issue our traces in sync with
    # httplib, which use print :(
    _debuglevel = 0

    def __init__(self, base, _from_transport=None, ca_certs=None):
        """Set the base path where files will be stored."""
        proto_match = re.match(r"^(https?)(\+\w+)?://", base)
        if not proto_match:
            raise AssertionError("not a http url: {!r}".format(base))
        self._unqualified_scheme = proto_match.group(1)
        super().__init__(base, _from_transport=_from_transport)
        self._medium = None
        # range hint is handled dynamically throughout the life
        # of the transport object. We start by trying multi-range
        # requests and if the server returns bogus results, we
        # retry with single range requests and, finally, we
        # forget about range if the server really can't
        # understand. Once acquired, this piece of info is
        # propagated to clones.
        if _from_transport is not None:
            self._range_hint = _from_transport._range_hint
            self._opener = _from_transport._opener
        else:
            self._range_hint = "multi"
            self._opener = Opener(
                report_activity=self._report_activity, ca_certs=ca_certs
            )

    def request(self, method, url, fields=None, headers=None, **urlopen_kw):
        body = urlopen_kw.pop("body", None)
        if fields is not None:
            data = urlencode(fields).encode()
            if body is not None:
                raise ValueError("body and fields are mutually exclusive")
        else:
            data = body
        if headers is None:
            headers = {}
        request = Request(method, url, data, headers)
        request.follow_redirections = urlopen_kw.pop("retries", 0) > 0
        if urlopen_kw:
            raise NotImplementedError(
                "unknown arguments: {!r}".format(urlopen_kw.keys())
            )
        connection = self._get_connection()
        if connection is not None:
            # Give back shared info
            request.connection = connection
            (auth, proxy_auth) = self._get_credentials()
            # Clean the httplib.HTTPConnection pipeline in case the previous
            # request couldn't do it
            connection.cleanup_pipe()
        else:
            # First request, initialize credentials.
            # scheme and realm will be set by the _urllib2_wrappers.AuthHandler
            auth = self._create_auth()
            # Proxy initialization will be done by the first proxied request
            proxy_auth = {}
        # Ensure authentication info is provided
        request.auth = auth
        request.proxy_auth = proxy_auth

        if self._debuglevel > 0:
            print(
                "perform: {} base: {}, url: {}".format(
                    request.method, self.base, request.get_full_url()
                )
            )
        response = self._opener.open(request)
        if self._get_connection() is not request.connection:
            # First connection or reconnection
            self._set_connection(request.connection, (request.auth, request.proxy_auth))
        else:
            # http may change the credentials while keeping the
            # connection opened
            self._update_credentials((request.auth, request.proxy_auth))

        code = response.code
        if request.follow_redirections is False and code in (301, 302, 303, 307, 308):
            raise errors.RedirectRequested(
                request.get_full_url(),
                request.redirected_to,
                is_permanent=(code in (301, 308)),
            )

        if request.redirected_to is not None:
            trace.mutter(
                "redirected from: {} to: {}".format(
                    request.get_full_url(), request.redirected_to
                )
            )

        class Urllib3LikeResponse:
            def __init__(self, actual):
                self._actual = actual
                self._data = None

            def getheader(self, name, default=None):
                if self._actual.headers is None:
                    raise http.client.ResponseNotReady()
                return self._actual.headers.get(name, default)

            def getheaders(self):
                if self._actual.headers is None:
                    raise http.client.ResponseNotReady()
                return list(self._actual.headers.items())

            @property
            def status(self):
                return self._actual.code

            @property
            def reason(self):
                return self._actual.reason

            @property
            def data(self):
                if self._data is None:
                    self._data = self._actual.read()
                return self._data

            @property
            def text(self):
                if self.status == 204:
                    return None
                from email.message import EmailMessage

                msg = EmailMessage()
                msg["content-type"] = self._actual.headers["Content-Type"]
                charset = msg["content-type"].params.get("charset")
                if charset:
                    return self.data.decode(charset)
                else:
                    return self.data.decode()

            def read(self, amt=None):
                if amt is None and "evil" in debug.debug_flags:
                    mutter_callsite(4, "reading full response.")
                return self._actual.read(amt)

            def readlines(self):
                return self._actual.readlines()

            def readline(self, size=-1):
                return self._actual.readline(size)

        return Urllib3LikeResponse(response)

    def disconnect(self):
        connection = self._get_connection()
        if connection is not None:
            connection.close()

    def has(self, relpath):
        """Does the target location exist?"""
        response = self._head(relpath)

        code = response.status
        if code == 200:  # "ok",
            return True
        else:
            return False

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        _code, response_file = self._get(relpath, None)
        return response_file

    def _get(self, relpath, offsets, tail_amount=0):
        """Get a file, or part of a file.

        :param relpath: Path relative to transport base URL
        :param offsets: None to get the whole file;
            or  a list of _CoalescedOffset to fetch parts of a file.
        :param tail_amount: The amount to get from the end of the file.

        :returns: (http_code, result_file)
        """
        abspath = self._remote_path(relpath)
        headers = {}
        if offsets or tail_amount:
            range_header = self._attempted_range_header(offsets, tail_amount)
            if range_header is not None:
                bytes = "bytes=" + range_header
                headers = {"Range": bytes}
        else:
            range_header = None

        response = self.request("GET", abspath, headers=headers)

        if response.status == 404:  # not found
            raise NoSuchFile(abspath)
        elif response.status == 416:
            # We don't know which, but one of the ranges we specified was
            # wrong.
            raise errors.InvalidHttpRange(
                abspath, range_header, "Server return code %d" % response.status
            )
        elif response.status == 400:
            if range_header:
                # We don't know which, but one of the ranges we specified was
                # wrong.
                raise errors.InvalidHttpRange(
                    abspath, range_header, "Server return code %d" % response.status
                )
            else:
                raise errors.BadHttpRequest(abspath, response.reason)
        elif response.status not in (200, 206):
            raise errors.UnexpectedHttpStatus(
                abspath, response.status, headers=response.getheaders()
            )

        data = handle_response(abspath, response.status, response.getheader, response)
        return response.status, data

    def _remote_path(self, relpath):
        """See ConnectedTransport._remote_path.

        user and passwords are not embedded in the path provided to the server.
        """
        url = self._parsed_url.clone(relpath)
        url.user = url.quoted_user = None
        url.password = url.quoted_password = None
        url.scheme = self._unqualified_scheme
        return str(url)

    def _create_auth(self):
        """Returns a dict containing the credentials provided at build time."""
        auth = {
            "host": self._parsed_url.host,
            "port": self._parsed_url.port,
            "user": self._parsed_url.user,
            "password": self._parsed_url.password,
            "protocol": self._unqualified_scheme,
            "path": self._parsed_url.path,
        }
        return auth

    def get_smart_medium(self):
        """See Transport.get_smart_medium."""
        if self._medium is None:
            # Since medium holds some state (smart server probing at least), we
            # need to keep it around. Note that this is needed because medium
            # has the same 'base' attribute as the transport so it can't be
            # shared between transports having different bases.
            self._medium = SmartClientHTTPMedium(self)
        return self._medium

    def _degrade_range_hint(self, relpath, ranges):
        if self._range_hint == "multi":
            self._range_hint = "single"
            mutter('Retry "{}" with single range request'.format(relpath))
        elif self._range_hint == "single":
            self._range_hint = None
            mutter('Retry "{}" without ranges'.format(relpath))
        else:
            # We tried all the tricks, but nothing worked, caller must reraise.
            return False
        return True

    # _coalesce_offsets is a helper for readv, it try to combine ranges without
    # degrading readv performances. _bytes_to_read_before_seek is the value
    # used for the limit parameter and has been tuned for other transports. For
    # HTTP, the name is inappropriate but the parameter is still useful and
    # helps reduce the number of chunks in the response. The overhead for a
    # chunk (headers, length, footer around the data itself is variable but
    # around 50 bytes. We use 128 to reduce the range specifiers that appear in
    # the header, some servers (notably Apache) enforce a maximum length for a
    # header and issue a '400: Bad request' error when too much ranges are
    # specified.
    _bytes_to_read_before_seek = 128
    # No limit on the offset number that get combined into one, we are trying
    # to avoid downloading the whole file.
    _max_readv_combine = 0
    # By default Apache has a limit of ~400 ranges before replying with a 400
    # Bad Request. So we go underneath that amount to be safe.
    _max_get_ranges = 200
    # We impose no limit on the range size. But see _pycurl.py for a different
    # use.
    _get_max_size = 0

    def _readv(self, relpath, offsets):
        """Get parts of the file at the given relative path.

        :param offsets: A list of (offset, size) tuples.
        :param return: A list or generator of (offset, data) tuples
        """
        # offsets may be a generator, we will iterate it several times, so
        # build a list
        offsets = list(offsets)

        try_again = True
        retried_offset = None
        while try_again:
            try_again = False

            # Coalesce the offsets to minimize the GET requests issued
            sorted_offsets = sorted(offsets)
            coalesced = self._coalesce_offsets(
                sorted_offsets,
                limit=self._max_readv_combine,
                fudge_factor=self._bytes_to_read_before_seek,
                max_size=self._get_max_size,
            )

            # Turn it into a list, we will iterate it several times
            coalesced = list(coalesced)
            if "http" in debug.debug_flags:
                mutter(
                    "http readv of %s  offsets => %s collapsed %s",
                    relpath,
                    len(offsets),
                    len(coalesced),
                )

            # Cache the data read, but only until it's been used
            data_map = {}
            # We will iterate on the data received from the GET requests and
            # serve the corresponding offsets respecting the initial order. We
            # need an offset iterator for that.
            iter_offsets = iter(offsets)
            try:
                cur_offset_and_size = next(iter_offsets)
            except StopIteration:
                return

            try:
                for cur_coal, rfile in self._coalesce_readv(relpath, coalesced):
                    # Split the received chunk
                    for offset, size in cur_coal.ranges:
                        start = cur_coal.start + offset
                        rfile.seek(start, os.SEEK_SET)
                        data = rfile.read(size)
                        data_len = len(data)
                        if data_len != size:
                            raise errors.ShortReadvError(
                                relpath, start, size, actual=data_len
                            )
                        if (start, size) == cur_offset_and_size:
                            # The offset requested are sorted as the coalesced
                            # ones, no need to cache. Win !
                            yield cur_offset_and_size[0], data
                            try:
                                cur_offset_and_size = next(iter_offsets)
                            except StopIteration:
                                return
                        else:
                            # Different sorting. We need to cache.
                            data_map[(start, size)] = data

                    # Yield everything we can
                    while cur_offset_and_size in data_map:
                        # Clean the cached data since we use it
                        # XXX: will break if offsets contains duplicates --
                        # vila20071129
                        this_data = data_map.pop(cur_offset_and_size)
                        yield cur_offset_and_size[0], this_data
                        try:
                            cur_offset_and_size = next(iter_offsets)
                        except StopIteration:
                            return

            except (
                errors.ShortReadvError,
                errors.InvalidRange,
                errors.InvalidHttpRange,
                errors.HttpBoundaryMissing,
            ) as e:
                mutter("Exception %r: %s during http._readv", e, e)
                if (
                    not isinstance(e, errors.ShortReadvError)
                    or retried_offset == cur_offset_and_size
                ):
                    # We don't degrade the range hint for ShortReadvError since
                    # they do not indicate a problem with the server ability to
                    # handle ranges. Except when we fail to get back a required
                    # offset twice in a row. In that case, falling back to
                    # single range or whole file should help.
                    if not self._degrade_range_hint(relpath, coalesced):
                        raise
                # Some offsets may have been already processed, so we retry
                # only the unsuccessful ones.
                offsets = [cur_offset_and_size] + list(iter_offsets)
                retried_offset = cur_offset_and_size
                try_again = True

    def _coalesce_readv(self, relpath, coalesced):
        """Issue several GET requests to satisfy the coalesced offsets."""

        def get_and_yield(relpath, coalesced):
            if coalesced:
                # Note that the _get below may raise
                # errors.InvalidHttpRange. It's the caller's responsibility to
                # decide how to retry since it may provide different coalesced
                # offsets.
                _code, rfile = self._get(relpath, coalesced)
                for coal in coalesced:
                    yield coal, rfile

        if self._range_hint is None:
            # Download whole file
            yield from get_and_yield(relpath, coalesced)
        else:
            total = len(coalesced)
            if self._range_hint == "multi":
                max_ranges = self._max_get_ranges
            elif self._range_hint == "single":
                max_ranges = total
            else:
                raise AssertionError(
                    "Unknown _range_hint {!r}".format(self._range_hint)
                )
            # TODO: Some web servers may ignore the range requests and return
            # the whole file, we may want to detect that and avoid further
            # requests.
            # Hint: test_readv_multiple_get_requests will fail once we do that
            cumul = 0
            ranges = []
            for coal in coalesced:
                if (
                    self._get_max_size > 0 and cumul + coal.length > self._get_max_size
                ) or len(ranges) >= max_ranges:
                    # Get that much and yield
                    yield from get_and_yield(relpath, ranges)
                    # Restart with the current offset
                    ranges = [coal]
                    cumul = coal.length
                else:
                    ranges.append(coal)
                    cumul += coal.length
            # Get the rest and yield
            yield from get_and_yield(relpath, ranges)

    def recommended_page_size(self):
        """See Transport.recommended_page_size().

        For HTTP we suggest a large page size to reduce the overhead
        introduced by latency.
        """
        return 64 * 1024

    def _post(self, body_bytes):
        """POST body_bytes to .bzr/smart on this transport.

        :returns: (response code, response body file-like object).
        """
        # TODO: Requiring all the body_bytes to be available at the beginning of
        # the POST may require large client buffers.  It would be nice to have
        # an interface that allows streaming via POST when possible (and
        # degrades to a local buffer when not).
        abspath = self._remote_path(".bzr/smart")
        response = self.request(
            "POST",
            abspath,
            body=body_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
        code = response.status
        data = handle_response(abspath, code, response.getheader, response)
        return code, data

    def _head(self, relpath):
        """Request the HEAD of a file.

        Performs the request and leaves callers handle the results.
        """
        abspath = self._remote_path(relpath)
        response = self.request("HEAD", abspath)
        if response.status not in (200, 404):
            raise errors.UnexpectedHttpStatus(
                abspath, response.status, headers=response.getheaders()
            )

        return response

        raise NotImplementedError(self._post)

    def put_file(self, relpath, f, mode=None):
        """Copy the file-like object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object.
        """
        raise errors.TransportNotPossible("http PUT not supported")

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        raise errors.TransportNotPossible("http does not support mkdir()")

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        raise errors.TransportNotPossible("http does not support rmdir()")

    def append_file(self, relpath, f, mode=None):
        """Append the text in the file-like object into the final
        location.
        """
        raise errors.TransportNotPossible("http does not support append()")

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to."""
        raise errors.TransportNotPossible("http does not support copy()")

    def copy_to(self, relpaths, other, mode=None, pb=None):
        """Copy a set of entries from self into another Transport.

        :param relpaths: A list/generator of entries to be copied.

        TODO: if other is LocalTransport, is it possible to
              do better than put(get())?
        """
        # At this point HttpTransport might be able to check and see if
        # the remote location is the same, and rather than download, and
        # then upload, it could just issue a remote copy_this command.
        if isinstance(other, HttpTransport):
            raise errors.TransportNotPossible("http cannot be the target of copy_to()")
        else:
            return super().copy_to(relpaths, other, mode=mode, pb=pb)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to."""
        raise errors.TransportNotPossible("http does not support move()")

    def delete(self, relpath):
        """Delete the item at relpath."""
        raise errors.TransportNotPossible("http does not support delete()")

    def external_url(self):
        """See breezy.transport.Transport.external_url."""
        # HTTP URL's are externally usable as long as they don't mention their
        # implementation qualifier
        url = self._parsed_url.clone()
        url.scheme = self._unqualified_scheme
        return str(url)

    def is_readonly(self):
        """See Transport.is_readonly."""
        return True

    def listable(self):
        """See Transport.listable."""
        return False

    def stat(self, relpath):
        """Return the stat information for a file."""
        raise errors.TransportNotPossible("http does not support stat()")

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        :return: A lock object, which should be passed to Transport.unlock().
        """

        # The old RemoteBranch ignore lock for reading, so we will
        # continue that tradition and return a bogus lock object.
        class BogusLock:
            def __init__(self, path):
                self.path = path

            def unlock(self):
                pass

        return BogusLock(relpath)

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it.

        :return: A lock object, which should be passed to Transport.unlock()
        """
        raise errors.TransportNotPossible("http does not support lock_write()")

    def _attempted_range_header(self, offsets, tail_amount):
        """Prepare a HTTP Range header at a level the server should accept.

        :return: the range header representing offsets/tail_amount or None if
            no header can be built.
        """
        if self._range_hint == "multi":
            # Generate the header describing all offsets
            return self._range_header(offsets, tail_amount)
        elif self._range_hint == "single":
            # Combine all the requested ranges into a single
            # encompassing one
            if len(offsets) > 0:
                if tail_amount not in (0, None):
                    # Nothing we can do here to combine ranges with tail_amount
                    # in a single range, just returns None. The whole file
                    # should be downloaded.
                    return None
                else:
                    start = offsets[0].start
                    last = offsets[-1]
                    end = last.start + last.length - 1
                    whole = self._coalesce_offsets(
                        [(start, end - start + 1)], limit=0, fudge_factor=0
                    )
                    return self._range_header(list(whole), 0)
            else:
                # Only tail_amount, requested, leave range_header
                # do its work
                return self._range_header(offsets, tail_amount)
        else:
            return None

    @staticmethod
    def _range_header(ranges, tail_amount):
        """Turn a list of bytes ranges into a HTTP Range header value.

        :param ranges: A list of _CoalescedOffset
        :param tail_amount: The amount to get from the end of the file.

        :return: HTTP range header string.

        At least a non-empty ranges *or* a tail_amount must be
        provided.
        """
        strings = []
        for offset in ranges:
            strings.append("%d-%d" % (offset.start, offset.start + offset.length - 1))

        if tail_amount:
            strings.append("-%d" % tail_amount)

        return ",".join(strings)

    def _redirected_to(self, source, target):
        """Returns a transport suitable to re-issue a redirected request.

        :param source: The source url as returned by the server.
        :param target: The target url as returned by the server.

        The redirection can be handled only if the relpath involved is not
        renamed by the redirection.

        :returns: A transport
        :raise UnusableRedirect: when the URL can not be reinterpreted
        """
        parsed_source = self._split_url(source)
        parsed_target = self._split_url(target)
        pl = len(self._parsed_url.path)
        # determine the excess tail - the relative path that was in
        # the original request but not part of this transports' URL.
        excess_tail = parsed_source.path[pl:].strip("/")
        if not parsed_target.path.endswith(excess_tail):
            # The final part of the url has been renamed, we can't handle the
            # redirection.
            raise UnusableRedirect(source, target, "final part of the url was renamed")

        target_path = parsed_target.path
        if excess_tail:
            # Drop the tail that was in the redirect but not part of
            # the path of this transport.
            target_path = target_path[: -len(excess_tail)]

        if parsed_target.scheme in ("http", "https"):
            # Same protocol family (i.e. http[s]), we will preserve the same
            # http client implementation when a redirection occurs from one to
            # the other (otherwise users may be surprised that bzr switches
            # from one implementation to the other, and devs may suffer
            # debugging it).
            if (
                parsed_target.scheme == self._unqualified_scheme
                and parsed_target.host == self._parsed_url.host
                and parsed_target.port == self._parsed_url.port
                and (
                    parsed_target.user is None
                    or parsed_target.user == self._parsed_url.user
                )
            ):
                # If a user is specified, it should match, we don't care about
                # passwords, wrong passwords will be rejected anyway.
                return self.clone(target_path)
            else:
                # Rebuild the url preserving the scheme qualification and the
                # credentials (if they don't apply, the redirected to server
                # will tell us, but if they do apply, we avoid prompting the
                # user)
                redir_scheme = parsed_target.scheme
                new_url = self._unsplit_url(
                    redir_scheme,
                    self._parsed_url.user,
                    self._parsed_url.password,
                    parsed_target.host,
                    parsed_target.port,
                    target_path,
                )
                return transport.get_transport_from_url(new_url)
        else:
            # Redirected to a different protocol
            new_url = self._unsplit_url(
                parsed_target.scheme,
                parsed_target.user,
                parsed_target.password,
                parsed_target.host,
                parsed_target.port,
                target_path,
            )
            return transport.get_transport_from_url(new_url)

    def _options(self, relpath):
        abspath = self._remote_path(relpath)
        resp = self.request("OPTIONS", abspath)
        if resp.status == 404:
            raise NoSuchFile(abspath)
        if resp.status in (403, 405):
            raise errors.InvalidHttpResponse(
                abspath,
                "OPTIONS not supported or forbidden for remote URL",
                headers=resp.getheaders(),
            )
        return resp.getheaders()


# TODO: May be better located in smart/medium.py with the other
# SmartMedium classes
class SmartClientHTTPMedium(medium.SmartClientMedium):
    def __init__(self, http_transport):
        super().__init__(http_transport.base)
        # We don't want to create a circular reference between the http
        # transport and its associated medium. Since the transport will live
        # longer than the medium, the medium keep only a weak reference to its
        # transport.
        self._http_transport_ref = weakref.ref(http_transport)

    def get_request(self):
        return SmartClientHTTPMediumRequest(self)

    def should_probe(self):
        return True

    def remote_path_from_transport(self, transport):
        # Strip the optional 'bzr+' prefix from transport so it will have the
        # same scheme as self.
        transport_base = transport.base
        if transport_base.startswith("bzr+"):
            transport_base = transport_base[4:]
        rel_url = urlutils.relative_url(self.base, transport_base)
        return urlutils.unquote(rel_url)

    def send_http_smart_request(self, bytes):
        try:
            # Get back the http_transport hold by the weak reference
            t = self._http_transport_ref()
            code, body_filelike = t._post(bytes)
            if code != 200:
                raise errors.UnexpectedHttpStatus(t._remote_path(".bzr/smart"), code)
        except (errors.InvalidHttpResponse, errors.ConnectionReset) as e:
            raise errors.SmartProtocolError(str(e))
        return body_filelike

    def _report_activity(self, bytes, direction):
        """See SmartMedium._report_activity.

        Does nothing; the underlying plain HTTP transport will report the
        activity that this medium would report.
        """
        pass

    def disconnect(self):
        """See SmartClientMedium.disconnect()."""
        t = self._http_transport_ref()
        t.disconnect()


# TODO: May be better located in smart/medium.py with the other
# SmartMediumRequest classes
class SmartClientHTTPMediumRequest(medium.SmartClientMediumRequest):
    """A SmartClientMediumRequest that works with an HTTP medium."""

    def __init__(self, client_medium):
        medium.SmartClientMediumRequest.__init__(self, client_medium)
        self._buffer = b""

    def _accept_bytes(self, bytes):
        self._buffer += bytes

    def _finished_writing(self):
        data = self._medium.send_http_smart_request(self._buffer)
        self._response_body = data

    def _read_bytes(self, count):
        """See SmartClientMediumRequest._read_bytes."""
        return self._response_body.read(count)

    def _read_line(self):
        line, excess = medium._get_line(self._response_body.read)
        if excess != b"":
            raise AssertionError(
                "_get_line returned excess bytes, but this mediumrequest "
                "cannot handle excess. ({!r})".format(excess)
            )
        return line

    def _finished_reading(self):
        """See SmartClientMediumRequest._finished_reading."""
        pass


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from breezy.tests import features, http_server

    permutations = [
        (HttpTransport, http_server.HttpServer),
    ]
    if features.HTTPSServerFeature.available():
        from breezy.tests import https_server, ssl_certs

        class HTTPS_transport(HttpTransport):
            def __init__(self, base, _from_transport=None):
                super().__init__(
                    base,
                    _from_transport=_from_transport,
                    ca_certs=ssl_certs.build_path("ca.crt"),
                )

        permutations.append((HTTPS_transport, https_server.HTTPSServer))
    return permutations
