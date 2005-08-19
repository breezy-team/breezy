#! /usr/bin/python

# $Id: http_client.py 271 2004-10-09 10:50:59Z fredrik $
# a simple asynchronous http client (based on SimpleAsyncHTTP.py from
# "Python Standard Library" by Fredrik Lundh, O'Reilly 2001)
#
# HTTP/1.1 and GZIP support added in January 2003 by Fredrik Lundh.
#
# changes:
# 2004-08-26 fl   unified http callback
# 2004-10-09 fl   factored out gzip_consumer support
# 2005-07-08 mbp  experimental support for keepalive connections
#
# Copyright (c) 2001-2004 by Fredrik Lundh.  All rights reserved.
#



"""async/pipelined http client

Use
===

Users of this library pass in URLs they want to see, and consumer
objects that will receive the results at some point in the future.
Any number of requests may be queued up, and more may be added while
the download is in progress.

Requests can be both superscalar and superpipelined.  That is to say,
for each server there can be multiple sockets open, and each socket
may have more than one request in flight.

Design
======

There is a single DownloadManager, and a connection object for each
open socket.

Request/consumer pairs are maintained in queues.  Each connection has
a list of transmitted requests whose response has not yet been
received.  There is also a per-server list of requests that have not
yet been submitted.

When a connection is ready to transmit a new request, it takes one
from the unsubmitted list, sends the request, and adds the request to
its unfulfilled list.  This should happen when the connection has
space for more transmissions or when a new request is added by the
user.  If the connection terminates with unfulfilled requests they are
put back onto the unsubmitted list, to be retried elsewhere.

Because responses come back precisely in order, the connection always
knows what it should expect next: the response for the next
unfulfilled request.
"""

# Note that (as of ubuntu python 2.4.1) every socket.connect() call
# with a hostname does a remote DNS resolution, which is pretty sucky.
# Shouldn't there be a cache in glibc?  We should probably cache the
# address in, say, the DownloadManager.

# TODO: A default consumer operation that writes the received data
# into a file; by default the file is named the same as the last
# component of the URL.

# TODO: A utility function that is given a list of URLs, and downloads
# them all parallel/pipelined.  If any fail, it raises an exception
# (and discards the rest), or perhaps can be told to continue anyhow.
# The content is written into temporary files.  It returns a list of
# readable file objects.

import asyncore
import socket, string, time, sys
import StringIO
import mimetools, urlparse, urllib
import logging

logger = logging.getLogger('bzr.http_client')
debug = logger.debug
info = logger.info
error = logger.error


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


class DownloadManager(object):
    """Handles pipelined/overlapped downloads.

    Pass in a series of URLs with handlers to receive the response.
    This object will spread the requests over however many sockets
    seem useful.

    queued_requests
        Requests not assigned to any channel

    running_requests
        Currently assigned to a channel
    """
    def __init__(self):
        self.queued_requests = []
        # self.channel = HttpChannel('localhost', 8000, self)
        self.channels = []
        self.try_pipelined = False
        self.try_keepalive = False
        self.max_channels = 3


    def enqueue(self, url, consumer):
        self.queued_requests.append((url, consumer))
        self._wake_up_channel()


    def _channel_closed(self, channel):
        """Called by the channel when its socket closes.
        """
        self.channels.remove(channel)
        if self.queued_requests:
            # might recreate one
            self._wake_up_channel()


    def _make_channel(self):
        # proxy2 203.17.154.69
        # bazaar-ng.org 
        return HttpChannel('82.211.81.161', 80, self)
        # return HttpChannel('203.17.154.69', 8080, self)
        # return HttpChannel('localhost', 8000, self)
            

    def _wake_up_channel(self):
        """Try to wake up one channel to send the newly-added request.

        There may be more than one request pending, and this may cause
        more than one channel to take requests.  That's OK; some of
        them may be frustrated.
        """
        from random import shuffle, choice
        
        # first, wake up any idle channels
        done = False
        for ch in self.channels:
            if not ch.sent_requests:
                ch.take_one()
                done = True
        if done:
            debug("woke existing idle channel(s)")
            return

        if len(self.channels) < self.max_channels:
            newch = self._make_channel()
            self.channels.append(newch)
            newch.take_one()
            debug("created new channel")
            return

        if self.try_pipelined:
            # ask existing channels to take it
            debug("woke busy channel")
            choice(self.channels).take_one()


        debug("request left until a channel's idle")
        



    def run(self):
        """Run until all outstanding requests have been served."""
        #while self.running_requests or self.queued_requests \
        #          or not self.channel.is_idle():
        #    asyncore.loop(count=1)
        asyncore.loop()



class Response(object):
    """Holds in-flight response."""



def _parse_response_http10(header):
    from cStringIO import StringIO

    fp = StringIO(header)
    r = Response()

    r.status = fp.readline().split(" ", 2)
    r.headers = mimetools.Message(fp)

    # we can only(?) expect to do keepalive if we got either a 
    # content-length or chunked encoding; otherwise there's no way to know
    # when the content ends apart from through the connection close
    r.content_type = r.headers.get("content-type")
    try:
        r.content_length = int(r.headers.get("content-length"))
    except (ValueError, TypeError):
        r.content_length = None
    debug("seen content length of %r" % r.content_length)

    r.transfer_encoding = r.headers.get("transfer-encoding")
    r.content_encoding = r.headers.get("content-encoding")
    r.connection_reply = r.headers.get("connection")

    # TODO: pass status code to consumer?

    if r.transfer_encoding:
        raise NotImplementedError()

    if r.transfer_encoding:
        raise NotImplementedError()

    if int(r.status[1]) != 200:
        debug("can't handle response status %r" % r.status)
        raise NotImplementedError()

    if r.content_length == None:
        raise NotImplementedError()

    if r.content_length == 0:
        raise NotImplementedError()

    r.content_remaining = r.content_length                

    return r


    
    
        


class HttpChannel(asyncore.dispatcher_with_send):
    """One http socket, pipelining if possible."""
    # asynchronous http client

    user_agent = "http_client.py 1.3ka (based on effbot)"

    proxies = urllib.getproxies()

    def __init__(self, ip_host, ip_port, manager):
        asyncore.dispatcher_with_send.__init__(self)
        self.manager = manager

        # if a response header has been seen, this holds it
        self.response = None
        
        self.data = ""

        self.chunk_size = None

        self.timestamp = time.time()

        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        debug('connecting...')
        self.connect((ip_host, ip_port))

        # sent_requests holds (url, consumer) 
        self.sent_requests = []

        self._outbuf = ''


    def __repr__(self):
        return 'HttpChannel(local_port=%r)' % (self.getsockname(),)


    def is_idle(self):
        return (not self.sent_requests)


    def handle_connect(self):
        debug("connected")
        self.take_one()


    def take_one(self):
        """Accept one request from the manager if possible."""
        if self.manager.try_pipelined:
            if len(self.sent_requests) > 4:
                return
        else:
            if len(self.sent_requests) > 0:
                return 
        
        try:
            url, consumer = self.manager.queued_requests.pop(0)
            debug('request accepted by channel')
        except IndexError:
            return
        
        # TODO: If there are too many already in flight, don't take one.
        # TODO: If the socket's not writable (tx buffer full), don't take.
        self._push_request_http10(url, consumer)



    def _push_request_http10(self, url, consumer):
        """Send a request, and add it to the outstanding queue."""
        # TODO: check the url requested is appropriate for this connection

        # TODO: If there are too many requests outstanding or (less likely) the 
        # connection fails, queue it for later use.

        # TODO: Keep track of requests that have been sent but not yet fulfilled,
        # because we might need to retransmit them if the connection fails. (Or
        # should the caller do that?)

        request = self._form_request_http10(url)
        debug('send request for %s from %r' % (url, self))

        # dispatcher_with_send handles buffering the data until it can
        # be written, and hooks handle_write.

        self.send(request)

        self.sent_requests.append((url, consumer))


    def _form_request_http10(self, url):
        # TODO: get right vhost name
        request = [
            "GET %s HTTP/1.0" % (url),
            "Host: www.bazaar-ng.org",
            ]

        if self.manager.try_keepalive or self.manager.try_pipelined:
            request.extend([
                "Keep-Alive: 60", 
                "Connection: keep-alive",
                ])

        # make sure to include a user agent
        for header in request:
            if string.lower(header).startswith("user-agent:"):
                break
        else:
            request.append("User-Agent: %s" % self.user_agent)

        return string.join(request, "\r\n") + "\r\n\r\n"


    def handle_read(self):
        # handle incoming data
        data = self.recv(2048)

        self.data = self.data + data

        if len(data):
            debug('got %d bytes from socket' % len(data))
        else:
            debug('server closed connection')

        while self.data:
            consumer = self.sent_requests[0][1]
            if not self.response:
                # do not have a full response header yet

                # check if we've seen a full header
                debug('getting header for %s' % self.sent_requests[0][0])

                header = self.data.split("\r\n\r\n", 1)
                if len(header) <= 1:
                    return
                header, self.data = header

                self.response = _parse_response_http10(header)
                self.content_remaining = self.response.content_length

            if not self.data:
                return

            # we now know how many (more) content bytes we have, and how much
            # is in the data buffer. there are two main possibilities:
            # too much data, and some must be left behind containing the next
            # response headers, or too little, or possibly just right

            want = self.content_remaining
            if want > 0:
                got_data = self.data[:want]
                self.data = self.data[want:]
                
                assert got_data

                debug('pass back %d bytes of %s' % (len(got_data),
                                                    self.sent_requests[0][0]))
                consumer.feed(data)

                self.content_remaining -= len(got_data)

            if self.content_remaining == 0:
                del self.sent_requests[0]

                # reset lots of things and try to get the next response header
                if self.response.connection_reply == 'close':
                    debug('server requested close')
                    self.manager._channel_closed(self)
                    self.close()
                elif not self.manager.try_keepalive:
                    debug('no keepalive for this socket')
                    self.manager._channel_closed(self)
                    self.close()
                else:
                    debug("ready for next header...")
                    consumer.content_complete()
                    self.take_one()
                self.response = None



    def handle_close(self):
        debug('async told us of close on %r' % self)
        # if there are outstanding requests should probably reopen and 
        # retransmit, but if we're not making any progress then give up
        self.manager._channel_closed(self)
        self.close()


if __name__ == "__main__":
    class dummy_consumer:
        def __init__(self, url):
            self.url = url

        def feed(self, data):
            # print "feed", repr(data)
            # print "feed", repr(data[:20]), repr(data[-20:]), len(data)
            pass
            
        def error(self, err_info):
            import traceback
            traceback.print_exception(err_info[0], err_info[1], err_info[2])

        def content_complete(self):
            debug('content complete from %s' % self.url)
            

    logging.basicConfig(level=logging.DEBUG)

    mgr = DownloadManager()

    from bzrlib.branch import Branch
    revs = Branch('/home/mbp/work/bzr').revision_history()

        
    
#     for url in ['http://www.bazaar-ng.org/',
#                 'http://www.bazaar-ng.org/tutorial.html',
#                 'http://www.bazaar-ng.org/download.html',
#                 'http://www.bazaar-ng.org/bzr/bzr.dev/.bzr/revision-store/mbp@hope-20050415013653-3b3c9c3d33fae0a6.gz',
#                 ]:

    for rev in revs:
#        url = 'http://www.bazaar-ng.org/bzr/bzr.dev/.bzr/revision-store/' \
        url = 'http://www.bazaar-ng.org/bzr/bzr.dev/.bzr/inventory-store/' \
              + rev + '.gz'
        mgr.enqueue(url, dummy_consumer(url))

    mgr.run()
    
