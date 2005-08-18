# $Id: http_client.py 271 2004-10-09 10:50:59Z fredrik $
# a simple asynchronous http client (based on SimpleAsyncHTTP.py from
# "Python Standard Library" by Fredrik Lundh, O'Reilly 2001)
#
# HTTP/1.1 and GZIP support added in January 2003 by Fredrik Lundh.
#
# changes:
# 2004-08-26 fl   unified http callback
# 2004-10-09 fl   factored out gzip_consumer support
#
# Copyright (c) 2001-2004 by Fredrik Lundh.  All rights reserved.
#

import asyncore
import socket, string, time, sys
import StringIO
import mimetools, urlparse, urllib

try:
    from gzip_consumer import GzipConsumer
except ImportError:
    pass

##
# Close connection.   Request handlers can raise this exception to
# indicate that the connection should be closed.

class CloseConnection(Exception):
    pass

##
# Redirect connection.  Request handlers can raise this exception to
# indicate that the a new request should be issued.

class Redirect(CloseConnection):
    def __init__(self, location):
        self.location = location

class Request(object):
    """This keeps track of all the information for a single request.
    """

    user_agent = "http_client.py 1.2 (http://effbot.org/zone)"
    http_version = "1.1"
    proxies = urllib.getproxies()

    def __init__(self, uri, consumer, extra_headers=None):
        self.consumer = consumer
        # turn the uri into a valid request
        scheme, host, path, params, query, fragment = urlparse.urlparse(uri)

        self.scheme = scheme
        self.host = host

        # get proxy settings, if any
        proxy = self.proxies.get(scheme)
        self.proxy = proxy

        if not path:
            path = "/"
        if params:
            path = path + ";" + params
        if query:
            path = path + "?" + query
        if proxy:
            path = scheme + "://" + self.host + path

        self.path = path

        # It turns out Content-Length isn't sufficient
        # to allow pipelining. Simply required.
        # So we will be extra stingy, and require the
        # response to also be HTTP/1.1 to enable pipelining
        self.http_1_1 = False
        self.status = None
        self.header = None

        self.bytes_in = 0
        self.bytes_out = 0

        self.content_type = None
        self.content_length = None
        self.content_encoding = None
        self.transfer_encoding = None

        self.data = ""

        self.chunk_size = None

        self.timestamp = time.time()

        self.extra_headers = extra_headers
        self.requested = False

    def http_request(self, conn):
        """Place the actual http request on the server"""
        # connection succeeded

        request = [
            "GET %s HTTP/%s" % (self.path, self.http_version),
            "Host: %s" % self.host,
            ]

        if False and GzipConsumer:
            request.append("Accept-Encoding: gzip")

        if self.extra_headers:
            request.extend(self.extra_headers)

        # make sure to include a user agent
        for header in request:
            if string.lower(header).startswith("user-agent:"):
                break
        else:
            request.append("User-Agent: %s" % self.user_agent)

        request = string.join(request, "\r\n") + "\r\n\r\n"

        conn.send(request)

        self.bytes_out = self.bytes_out + len(request)
        self.requested = True

    def add_data(self, data):
        """Some data has been downloaded, let the consumer know.
        :return: True- download is completed, there may be extra data in self.data which
                       should be transfered to the next item
                 False- download failed
                 None- continue downloading
        """

        self.data = self.data + data
        self.bytes_in = self.bytes_in + len(data)

        while self.data:

            if not self.header:
                # check if we've seen a full header

                header = self.data.split("\r\n\r\n", 1)
                if len(header) <= 1:
                    return
                header, self.data = header

                # parse header
                fp = StringIO.StringIO(header)
                self.status = fp.readline().split(" ", 2)
                self.header = mimetools.Message(fp)

                if self.status[0] == 'HTTP/1.1':
                    self.http_1_1 = True
                else:
                    self.http_1_1 = False

                # get http headers
                self.content_type = self.header.get("content-type")
                try:
                    self.content_length = int(
                        self.header.get("content-length")
                        )
                except (ValueError, TypeError):
                    self.content_length = None
                self.original_content_length = self.content_length
                self.transfer_encoding = self.header.get("transfer-encoding")
                self.content_encoding = self.header.get("content-encoding")

                # if self.content_encoding == "gzip":
                #     # FIXME: report error if GzipConsumer is not available
                #     self.consumer = GzipConsumer(self.consumer)

                try:
                    self.consumer.http(1, self)
                except Redirect, v:
                    # redirect
                    if v.location:
                        do_request(
                            v.location, self.consumer, self.extra_headers
                            )
                    return True
                except CloseConnection:
                    return False

            if self.transfer_encoding == "chunked" and self.chunk_size is None:

                # strip off leading whitespace
                if self.data.startswith("\r\n"):
                    self.data = self.data[2:]

                chunk_size = self.data.split("\r\n", 1)
                if len(chunk_size) <= 1:
                    return
                chunk_size, self.data = chunk_size

                try:
                    self.chunk_size = int(chunk_size, 16)
                    if self.chunk_size <= 0:
                        raise ValueError
                except ValueError:
                    self.consumer.close()
                    return False

            if not self.data:
                return

            data = self.data
            self.data = ""

            chunk_size = self.chunk_size or len(data)

            # Make sure to only feed the consumer whatever is left for
            # this file.
            if self.content_length:
                if chunk_size > self.content_length:
                    chunk_size = self.content_length

            if chunk_size < len(data):
                self.data = data[chunk_size:]
                data = data[:chunk_size]
                self.chunk_size = None
            else:
                self.chunk_size = chunk_size - len(data)
                if self.chunk_size <= 0:
                    self.chunk_size = None

            if data:
                self.consumer.feed(data)

            if self.content_length:
                self.content_length -= chunk_size
                if self.content_length <= 0:
                    self.consumer.close()
                    return True


##
# Asynchronous HTTP/1.1 client.

class async_http(asyncore.dispatcher_with_send):
    """Asynchronous HTTP client.
    This client keeps a queue of files to download, and
    tries to asynchronously (and pipelined) download them,
    alerting the consumer as bits are downloaded.
    """

    max_requests = 4

    def __init__(self, scheme, host):
        """Connect to the given host, extra requests are made on the
        add_request member function.

        :param scheme: The connection method, such as http/https, currently
                       we only support http
        :param host:   The host to connect to, either a proxy, or the actual host.
        """
        asyncore.dispatcher_with_send.__init__(self)

        # use origin host
        self.scheme = scheme
        self.host = host

        assert scheme == "http", "only supports HTTP requests (%s)" % scheme

        self._connected = False
        self._queue = []
        self._current = None

    def _connect(self):
        # get port number
        host = self.host
        try:
            host, port = self.host.split(":", 1)
            port = int(port)
        except (TypeError, ValueError):
            port = 80 # default port

        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.connect((host, port))
            self._connected = True
        except socket.error:
            self.handle_error()

    def _close(self):
        if self._connected:
            self.close()
        self._connected = False

    def _request_next(self):
        extra_data = None
        if self._current:
            extra_data = self._current.data
        if len(self._queue) > 0:
            self._current = self._queue.pop(0)
            if not self._current.requested:
                self._current.http_request(self)
            if extra_data:
                self._update_current(extra_data)
        else:
            # TODO: Consider some sort of delayed closing,
            # rather than closing the instant the
            # queue is empty. But I don't know any way
            # under async_core to be alerted at a later time.
            # If this were a thread, I would sleep, waking
            # up to check for more work, and eventually timing
            # out and disconnecting.
            self._close()

    def _update_current(self, data):
        res = self._current.add_data(data)
        if res is None:
            # Downloading is continuing
            if self._current.original_content_length and self._current.http_1_1:
                # We can pipeline our requests, since we
                # are getting a content_length count back
                for i, r in enumerate(self._queue[:self.max_requests-1]):
                    if not r.requested:
                        r.http_request(self)
            return
        if res:
            # We finished downloading the last file
            self._request_next()
        else:
            # There was a failure
            self.handle_error()

    def add_request(self, request):
        """Add a new Request into the queue."""
        self._queue.append(request)
        if not self._connected:
            self._connect()

    def handle_connect(self):
        self._request_next()

    def handle_expt(self):
        # connection failed (windows); notify consumer
        assert self._current

        if sys.platform == "win32":
            self._close()
            self._current.consumer.http(0, self._current)

    def handle_read(self):
        # handle incoming data
        assert self._current

        data = self.recv(2048)

        self._update_current(data)


    def handle_close(self):
        """When does this event occur? Is it okay to start the next entry in the queue
        (possibly reconnecting), or is this an indication that we should stop?
        """
        if self._current:
            self._current.consumer.close()
        self._close()
        if len(self._queue) > 0:
            self._connect()

    def handle_error(self):
        if self._current:
            self._current.consumer.http(0, self._current, sys.exc_info())
        # Should this be broadcast to all other items waiting in the queue?
        self._close()

_connections = {}

def do_request(uri, consumer, extra_headers=None):
    global _connections
    request = Request(uri, consumer, extra_headers)

    scheme = request.scheme
    host = request.host
    if request.proxy:
        host = request.proxy
    key = (scheme, host)
    if not _connections.has_key(key):
        _connections[key] = async_http(scheme, host)

    _connections[key].add_request(request)

    return request

if __name__ == "__main__":
    class dummy_consumer:
        def feed(self, data):
            # print "feed", repr(data)
            print "feed", repr(data[:20]), repr(data[-20:]), len(data)
        def close(self):
            print "close"
        def http(self, ok, connection, *args, **kwargs):
            print ok, connection, args, kwargs
            print "status", connection.status
            print "header", connection.header
    if len(sys.argv) < 2:
        do_request('http://www.cnn.com/', dummy_consumer())
    else:
        for url in sys.argv[1:]:
            do_request(url, dummy_consumer())
    asyncore.loop()
