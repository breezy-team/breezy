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

##
# Asynchronous HTTP/1.1 client.

class async_http(asyncore.dispatcher_with_send):
    # asynchronous http client

    user_agent = "http_client.py 1.2 (http://effbot.org/zone)"
    http_version = "1.1"

    proxies = urllib.getproxies()

    def __init__(self, uri, consumer, extra_headers=None):
        asyncore.dispatcher_with_send.__init__(self)

        # turn the uri into a valid request
        scheme, host, path, params, query, fragment = urlparse.urlparse(uri)

        # use origin host
        self.host = host

        # get proxy settings, if any
        proxy = self.proxies.get(scheme)
        if proxy:
            scheme, host, x, x, x, x = urlparse.urlparse(proxy)

        assert scheme == "http", "only supports HTTP requests (%s)" % scheme

        if not path:
            path = "/"
        if params:
            path = path + ";" + params
        if query:
            path = path + "?" + query
        if proxy:
            path = scheme + "://" + self.host + path

        self.path = path

        # get port number
        try:
            host, port = host.split(":", 1)
            port = int(port)
        except (TypeError, ValueError):
            port = 80 # default port

        self.consumer = consumer

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

        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.connect((host, port))
        except socket.error:
            self.consumer.http(0, self, sys.exc_info())

    def handle_connect(self):
        # connection succeeded

        request = [
            "GET %s HTTP/%s" % (self.path, self.http_version),
            "Host: %s" % self.host,
            ]

        if GzipConsumer:
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

        self.send(request)

        self.bytes_out = self.bytes_out + len(request)

    def handle_expt(self):
        # connection failed (windows); notify consumer

        if sys.platform == "win32":
            self.close()
            self.consumer.http(0, self)

    def handle_read(self):
        # handle incoming data

        data = self.recv(2048)

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

                # get http headers
                self.content_type = self.header.get("content-type")
                try:
                    self.content_length = int(
                        self.header.get("content-length")
                        )
                except (ValueError, TypeError):
                    self.content_length = None
                self.transfer_encoding = self.header.get("transfer-encoding")
                self.content_encoding = self.header.get("content-encoding")

                if self.content_encoding == "gzip":
                    # FIXME: report error if GzipConsumer is not available
                    self.consumer = GzipConsumer(self.consumer)

                try:
                    self.consumer.http(1, self)
                except Redirect, v:
                    # redirect
                    if v.location:
                        do_request(
                            v.location, self.consumer, self.extra_headers
                            )
                    self.close()
                    return
                except CloseConnection:
                    self.close()
                    return

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
                    return self.handle_close()

            if not self.data:
                return

            data = self.data
            self.data = ""

            chunk_size = self.chunk_size or len(data)

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
                    return self.handle_close()

    def handle_close(self):
        self.consumer.close()
        self.close()

    def handle_error(self):
        self.consumer.http(0, self, sys.exc_info())
        self.close()

def do_request(uri, consumer, extra_headers=None):

    return async_http(uri, consumer, extra_headers)

if __name__ == "__main__":
    class dummy_consumer:
        def feed(self, data):
            # print "feed", repr(data)
            print "feed", repr(data[:20]), repr(data[-20:]), len(data)
        def close(self):
            print "close"
        def http(self, ok, connection, **args):
            print ok, connection, args
            print "status", connection.status
            print "header", connection.header
    try:
        url = sys.argv[1]
    except IndexError:
        url = "http://www.cnn.com/"
    do_request(url, dummy_consumer())
    asyncore.loop()
