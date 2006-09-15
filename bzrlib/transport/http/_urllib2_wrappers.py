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

"""Implementaion of urllib2 tailored to bzr needs

This file re-implements the urllib2 class hierarchy with custom classes.

For instance, we create a new HTTPConnection and HTTPSConnection that inherit
from the original urllib2.HTTP(s)Connection objects, but also have a new base
which implements a custom getresponse and fake_close handlers.

And then we implement custom HTTPHandler and HTTPSHandler classes, that use
the custom HTTPConnection classes.

We have a custom Response class, which lets us maintain a keep-alive
connection even for requests that urllib2 doesn't expect to contain body data.

And a custom Request class that lets us track redirections, and send
authentication data without requiring an extra round trip to get rejected by
the server. We also create a Request hierarchy, to make it clear what type
of request is being made.
"""


DEBUG = 0

# TODO: Handle the user and password cleanly: do not force the
# user to provide them in the url (at least for the
# password). Have a look at the password_manager classes. Tip: it
# may be possible to share the password_manager between across
# all transports by prefixing the relm by the protocol used
# (especially if other protocols do not use realms). See
# PasswordManager below.

# FIXME: Oversimplifying, two kind of exceptions should be
# raised, once a request is issued: URLError before we have been
# able to process the response, HTTPError after that. Process the
# response means we are able to leave the socket clean, so if we
# are not able to do that, we should close the connection. The
# actual code more or less do that, tests should be written to
# ensur that.

import httplib
import socket
import urllib
import urllib2
import urlparse

from bzrlib import (
    __version__ as bzrlib_version,
    )
from bzrlib.errors import (
    BzrError,
    ConnectionError,
    NoSuchFile,
    )


# We define our own Response class to keep our httplib pipe clean
class Response(httplib.HTTPResponse):
    """Custom HTTPResponse, to avoid needing to decorate.

    httplib prefers to decorate the returned objects, rather
    than using a custom object.
    """

    def __init__(self, *args, **kwargs):
        httplib.HTTPResponse.__init__(self, *args, **kwargs)

    def begin(self):
        """Begin to read the response from the server.

        httplib assumes that some responses get no content and do
        not even attempt to read the body in that case, leaving
        the body in the socket, blocking the next request. Let's
        try to workaround that.
        """
        httplib.HTTPResponse.begin(self)
        if self.status in (999,
                           301,
                           302, 303, 307,
                           401, ):
            body = self.fp.read(self.length)
            #print "Consumed body: [%s]" % body
            self.close()


# Not inheriting from 'object' because httplib.HTTPConnection doesn't.
class AbstractHTTPConnection:
    """A custom HTTP(S) Connection, which can reset itself on a bad response"""

    response_class = Response

    def getresponse(self):
        """Get the response from the server.

        If the response can't be acquired, the request itself may
        as well be considered aborted, so we reset the connection
        object to be able to send a new request.

        httplib should be responsible for that, it's not
        currently (python 2.4.3 httplib (not versioned) , so we
        try to workaround it.
        """
        try:
            return httplib.HTTPConnection.getresponse(self)
        # TODO: A bit of selection on different exceptions may be
        # of good taste
        except Exception, e:
            if self.debuglevel > 0:
                print 'On exception: [%r]' % e
                print '  Reset connection: [%s]' % self
            # Things look really weird, let's start again
            self.close()
            raise

    def fake_close(self):
        """Make the connection believes the response have been fully handled.

        That makes the httplib.HTTPConnection happy
        """
        # Preserve our preciousss
        sock = self.sock
        self.sock = None
        self.close()
        self.sock = sock


class HTTPConnection(AbstractHTTPConnection, httplib.HTTPConnection):
    pass


class HTTPSConnection(AbstractHTTPConnection, httplib.HTTPSConnection):
    pass


class Request(urllib2.Request):
    """A custom Request object.

    urllib2 determines the request method heuristically (based on
    the presence or absence of data). We set the method
    statically.

    Also, the Request object tracks the connection the request will
    be made on.
    """

    def __init__(self, method, url, data=None, headers={},
                 origin_req_host=None, unverifiable=False,
                 connection=None, parent=None,):
        # urllib2.Request will be confused if we don't extract
        # authentification info before building the request
        url, self.user, self.password = self.extract_auth(url)
        urllib2.Request.__init__(self, url, data, headers,
                                 origin_req_host, unverifiable)
        self.method = method
        self.connection = connection
        # To handle redirections
        self.parent = parent
        self.redirected_to = None

    def extract_auth(self, url):
        """Extracts authentification information from url.

        Get user and password from url of the form: http://user:pass@host/path
        """
        scheme, netloc, path, query, fragment = urlparse.urlsplit(url)

        if '@' in netloc:
            auth, netloc = netloc.split('@', 1)
            if ':' in auth:
                user, password = auth.split(':', 1)
            else:
                user, password = auth, None
            user = urllib.unquote(user)
            if password is not None:
                password = urllib.unquote(password)
        else:
            user = None
            password = None

        url = urlparse.urlunsplit((scheme, netloc, path, query, fragment))

        return url, user, password

    def get_method(self):
        return self.method


# The urlib2.xxxAuthHandler handle the authentification of the
# requests, to do that, they need an urllib2 PasswordManager *at
# build time*.

# We want to associate such PasswordManager objects to the
# connection, so that they can be reused (otherwise we will have
# to prompt the user for its password at each connection).

# TODO: Is there a way to share the password manager with other
# protocols ? By prefixing th realm with the protocol ? A
# different password for the same user may be required on the
# same host for different protocol/host/directories combination.
class PasswordManager(urllib2.HTTPPasswordMgrWithDefaultRealm):

    def __init__(self):
        urllib2.HTTPPasswordMgrWithDefaultRealm.__init__(self)

    # TODO: jam 20060915 This manager should implement find_user_password
    #       so that even if we don't supply username in the url, if the
    #       site requests a password we prompt the user for one.


class ConnectionHandler(urllib2.BaseHandler):
    """Provides connection-sharing by pre-processing requests.

    urllib2 provides no way to access the HTTPConnection object
    internally used. But we need it in order to achieve
    connection sharing. So, we add it to the request just before
    it is processed, and then we override the do_open method for
    http[s] requests.
    """

    handler_order = 1000 # after all pre-processings
    _connection_of = {} # map connections by host

    # TODO: We don't want a global cache that can interact badly
    # with the test suite, but being able to share connections on
    # the same (host IP, port) combination can be good even
    # inside a single tranport (some redirections can benefit
    # from it, bazaar-ng.org and bazaar-vcs.org are two virtual
    # hosts on the same IP for example). So we may activate the
    # cache as currently it is used inside one Transport at a
    # time.
    # jam 20060915: I think most of this get_key stuff can be removed
    #               since we now properly share the connection between
    #               clones of the same Transport.
    _cache_activated = False

    def get_key(self, connection):
        """Returns the key for the connection in the cache"""
        return '%s:%d' % (connection.host, connection.port)

    def create_connection(self, request, http_connection_class):
        host = request.get_host()
        if not host:
            raise urllib2.URLError('no host given')

        # We create a connection (but it will not connect yet) to
        # be able to get host and take default port into account
        # (request don't do that) to avoid having different
        # connections for http://host and http://host:80
        connection = http_connection_class(host)
        if self._cache_activated:
            key = self.get_key(connection)
            if key not in self._connection_of:
                self._connection_of[key] = connection
            else:
                connection = self._connection_of[key]

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
        else:
            if self._cache_activated:
                # Capture the precioussss
                key = self.get_key(connection)
                if key not in self._connection_of:
                    self._connection_of[key] = connection

        # All connections will pass here, propagate debug level
        connection.set_debuglevel(DEBUG)
        return request

    def http_request(self, request):
        return self.capture_connection(request, HTTPConnection)

    def https_request(self, request):
        return self.capture_connection(request, HTTPSConnection)


class AbstractHTTPHandler(urllib2.AbstractHTTPHandler):
    """A custom handler for HTTP(S) requests.

    We overrive urllib2.AbstractHTTPHandler to get a better
    control of the connection, the ability to implement new
    request types and return a response able to cope with
    persistent connections.
    """

    # We change our order to be before urllib2 HTTP[S]Handlers
    # and choosed instead of them (the first http_open called
    # wins).
    handler_order = 400

    _default_headers = {'Pragma': 'no-cache',
                        'Cache-control': 'max-age=0',
                        'Connection': 'Keep-Alive',
                        'User-Agent': 'bzr/%s (urllib)' % bzrlib_version,
                        }

    def __init__(self):
        urllib2.AbstractHTTPHandler.__init__(self, debuglevel=0)

    # FIXME: This is the place where all the httplib exceptions
    # should be catched, translated into bzr errors or handled
    # accordingly (reset connection and try again or raise)
    def do_open(self, http_class, request, first_try=True):
        """See urllib2.AbstractHTTPHandler.do_open for the general idea.

        The request will be retried once if it fails.
        """
        connection = request.connection
        assert connection is not None, \
            'Cannot process a request without a connection'

        headers = self._default_headers.copy()
        headers.update(request.header_items())
        headers.update(request.unredirected_hdrs)
        try:
            connection._send_request(request.get_method(),
                                     request.get_selector(),
                                     # FIXME: implements 100-continue
                                     #None, # We don't send the body yet
                                     request.get_data(),
                                     headers)
        except socket.error, e:
            raise ConnectionError(msg= 'while sending %s %s:'
                                  % (request.get_method(),
                                     request.get_selector()),
                                  orig_error=e)
        if self._debuglevel > 0:
            print 'Request sent: [%r]' % request
        try:
            response = connection.getresponse()
            convert_to_addinfourl = True
        except httplib.BadStatusLine, e:
            # Presumably the server have borked the connection
            # for an unknown reason. Let's try again.
            if first_try:
                if self._debuglevel > 0:
                    print 'Received exception: [%r]' % e
                    print '  On connection: [%r]' % request.connection
                    method = request.get_method()
                    url = request.get_full_url()
                    print '  Will retry, %s %r' % (method, url)
                response = self.do_open(http_class, request, False)
                convert_to_addinfourl = False
            else:
                if self._debuglevel > 0:
                    print 'On connection: [%r]' % request.connection
                    method = request.get_method()
                    url = request.get_full_url()
                    print '  Failed again, %s %r' % (method, url)
                    print '  Will raise: [%r]' % e
                raise
        except urllib2.URLError, e:
            mutter('url error: %s, for %s url: %r',
                   e.reason, request.get_method(), url)
            raise
        # FIXME: The following is suspicious, it has been copied
        # from _urllib.py and should not occurs -- vila 20060913
        except (BzrError, IOError), e:
            mutter('io error: %s %s for %s url: %r',
                   e.errno, errno.errorcode.get(e.errno),
                   request.get_method(), url)
            raise TransportError(orig_error=e)

# FIXME: HTTPConnection does not fully support 100-continue (the
# server responses are just ignored)

#        if code == 100:
#            mutter('Will send the body')
#            # We can send the body now
#            body = request.get_data()
#            if body is None:
#                raise URLError("No data given")
#            connection.send(body)
#            response = connection.getresponse()

        if self._debuglevel > 0:
            print 'Receives response: %r' % response
            print '  For: %r(%r)' % (request.get_method(),
                                     request.get_full_url())

        if convert_to_addinfourl:
            # Shamelessly copied from urllib2
            req = request
            r = response
            r.recv = r.read
            fp = socket._fileobject(r)
            resp = urllib2.addinfourl(fp, r.msg, req.get_full_url())
            resp.code = r.status
            resp.msg = r.reason
            if self._debuglevel > 0:
                print 'Create addinfourl: %r' % resp
                print '  For: %r(%r)' % (request.get_method(),
                                         request.get_full_url())
        else:
            resp = response
        return resp

#       # we need titled headers in a dict but
#       # response.getheaders returns a list of (lower(header).
#       # Let's title that because most of bzr handle titled
#       # headers, but maybe we should switch to lowercased
#       # headers...
#        # jam 20060908: I think we actually expect the headers to
#        #       be similar to mimetools.Message object, which uses
#        #       case insensitive keys. It lowers() all requests.
#        #       My concern is that the code may not do perfect title case.
#        #       For example, it may use Content-type rather than Content-Type
#
#        # When we get rid of addinfourl, we must ensure that bzr
#        # always use titled headers and that any header received
#        # from server is also titled
#
#        headers = {}
#        for header, value in (response.getheaders()):
#            headers[header.title()] = value
#        # FIXME: Implements a secured .read method
#        response.code = response.status
#        response.headers = headers
#        return response


class HTTPHandler(AbstractHTTPHandler):
    """A custom handler that just thunks into HTTPConnection"""

    def http_open(self, request):
        return self.do_open(HTTPConnection, request)


class HTTPSHandler(AbstractHTTPHandler):
    """A custom handler that just thunks into HTTPSConnection"""

    def https_open(self, request):
        return self.do_open(HTTPSConnection, request)


class HTTPRedirectHandler(urllib2.HTTPRedirectHandler):
    """Handles redirect requests.

    We have to implement our own scheme because we use a specific
    Request object and because we want to implement a specific
    policy.
    """
    _debuglevel = DEBUG
    # RFC2616 says that only read requests should be redirected
    # without interacting with the user. But bzr use some
    # shortcuts to optimize against roundtrips which can leads to
    # write requests being issued before read requests of
    # containing dirs can be redirected. So we redirect write
    # requests in the same way which seems to respect the spirit
    # of the RFC if not its letter.

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """See urllib2.HTTPRedirectHandler.redirect_request"""
        # We would have preferred to update the request instead
        # of creating a new one, but the urllib2.Request object
        # has a too complicated creation process to provide a
        # simple enough equivalent update process. Instead, when
        # redirecting, we only update the original request with a
        # reference to the following request in the redirect
        # chain.

        # Some codes make no sense on out context and are treated
        # as errors:

        # 300: Multiple choices for different representations of
        #      the URI. Using that mechanisn with bzr will violate the
        #      protocol neutrality of Transport.

        # 304: Not modified (SHOULD only occurs with conditional
        #      GETs which are not used by our implementation)

        # 305: Use proxy. I can't imagine this one occurring in
        #      our context-- vila/20060909

        # 306: Unused (if the RFC says so...)

        # FIXME: If the code is 302 and the request is HEAD, we
        # may avoid a following the redirections if the intent is
        # to check the existence, we have a hint, now if we want
        # to be sure, we must follow the redirection. Let's do
        # that for now.

        if code in (301, 302, 303, 307):
            return Request(req.get_method(),newurl,
                           headers = req.headers,
                           origin_req_host = req.get_origin_req_host(),
                           unverifiable = True,
                           # TODO: It will be nice to be able to
                           # detect virtual hosts sharing the same
                           # IP address, that will allow us to
                           # share the same connection...
                           connection = None,
                           parent = req,
                           )
        else:
            raise urllib2.HTTPError(req.get_full_url(), code, msg, headers, fp)

    # Copied from urllib2 to be able to fake_close the associated
    # connection, *before* issuing the redirected request but
    # *after* having eventually raised an error
    def http_error_30x(self, req, fp, code, msg, headers):
        """Requests the redirected to URI"""
        # Some servers (incorrectly) return multiple Location headers
        # (so probably same goes for URI).  Use first header.

        # TODO: Once we get rid of addinfourl objects, the
        # following will need to be updated to use correct case
        # for headers.
        if 'location' in headers:
            newurl = headers.getheaders('location')[0]
        elif 'uri' in headers:
            newurl = headers.getheaders('uri')[0]
        else:
            return
        if self._debuglevel > 0:
            print 'Redirected to: %s' % newurl
        newurl = urlparse.urljoin(req.get_full_url(), newurl)

        # This call succeeds or raise an error. urllib2 returns
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
                raise urllib2.HTTPError(req.get_full_url(), code,
                                        self.inf_msg + msg, headers, fp)
        else:
            visited = redirected_req.redirect_dict = req.redirect_dict = {}
        visited[newurl] = visited.get(newurl, 0) + 1

        # We can close the fp now that we are sure that we won't
        # use it with HTTPError.
        fp.close()
        # We have all we need already in the response
        req.connection.fake_close()

        return self.parent.open(redirected_req)

    http_error_302 = http_error_303 = http_error_307 = http_error_30x

    def http_error_301(self, req, fp, code, msg, headers):
        response = self.http_error_30x(req, fp, code, msg, headers)
        # If one or several 301 response occur during the
        # redirection chain, we MUST update the original request
        # to indicate where the URI where finally found.

        original_req = req
        while original_req.parent is not None:
            original_req = original_req.parent
            if original_req.redirected_to is None:
                # Only the last occurring 301 should be taken
                # into account i.e. the first occurring here when
                # redirected_to has not yet been set.
                original_req.redirected_to = redirected_url
        return response


class HTTPErrorProcessor(urllib2.HTTPErrorProcessor):
    """Process HTTP error responses.

    We don't really process the errors, quite the contrary
    instead, we leave our Transport handle them.
    """
    handler_order = 1000  # after all other processing

    def http_response(self, request, response):
        code, msg, hdrs = response.code, response.msg, response.info()

        if code not in (200, # Ok
                        206, # Partial content
                        404, # Not found
                        ):
            response = self.parent.error('http', request, response,
                                         code, msg, hdrs)
        return response

    https_response = http_response


class HTTPDefaultErrorHandler(urllib2.HTTPDefaultErrorHandler):
    """Translate common errors into bzr Exceptions"""

    def http_error_default(self, req, fp, code, msg, hdrs):
        if code == 404:
            raise NoSuchFile(req.get_selector(),
                             extra=HTTPError(req.get_full_url(), code, msg,
                                             hdrs, fp))
        else:
            raise InvalidHttpResponse(url,
                                      'Unable to handle http code %d: %s'
                                      % (response.code, response.reason))

class Opener(object):
    """A wrapper around urllib2.build_opener

    Daughter classes can override to build their own specific opener
    """
    # TODO: Provides hooks for daugther classes.

    # This is a global password manager object, intended to be shared
    # by all instances of Opener. It is global so that users don't get
    # prompted for their passwords more than once.
    # TODO: jam 20060915 Consider making it only exist as long as the Opener 
    #       is alive, or possibly as long as a living Transport group.
    #       Consider a long-running gui: it may be better to prompt the
    #       user for the password from time to time, rather than caching
    #       the password indefinitely. At a minimum, the GUI should
    #       be able to set policy.
    password_manager = PasswordManager()

    def __init__(self,
                 connection=ConnectionHandler,
                 redirect=HTTPRedirectHandler,
                 error=HTTPErrorProcessor,):
        # TODO: Implements the necessary wrappers for the handlers
        # commented out below
        self._opener = urllib2.build_opener( \
            connection, redirect, error,
            #urllib2.ProxyHandler,
            urllib2.HTTPBasicAuthHandler(self.password_manager),
            #urllib2.HTTPDigestAuthHandler(self.password_manager),
            #urllib2.ProxyBasicAuthHandler,
            #urllib2.ProxyDigestAuthHandler,
            HTTPHandler,
            HTTPSHandler,
            HTTPDefaultErrorHandler,
            )
        self.open = self._opener.open
        if DEBUG > 0:
            import pprint
            pprint.pprint(self._opener.__dict__)

