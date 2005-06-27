# $Id: http_manager.py 270 2004-10-09 10:38:54Z fredrik $
# effnews http
#
# manage a set of http clients
#
# Copyright (c) 2001-2004 by Fredrik Lundh.  All rights reserved.
#

import asyncore, time
import http_client

class http_manager:

    max_connections = 8
    max_size = 1000000
    max_time = 60

    def __init__(self):
        self.queue = []

    def request(self, uri, consumer, extra_headers=None):
        self.queue.append((uri, consumer, extra_headers))

    def priority_request(self, uri, consumer, extra_headers=None):
        self.queue.insert(0, (uri, consumer, extra_headers))

    def purge(self):
        for channel in asyncore.socket_map.values():
            channel.close()
        del self.queue[:]

    def prioritize(self, priority_uri):
        i = 0
        for uri, consumer, extra_headers in self.queue:
            if uri == priority_uri:
                del self.queue[i]
                self.priority_request(uri, consumer, extra_headers)
                return
            i = i + 1

    def poll(self, timeout=0.1):
        # sanity checks
        now = time.time()
        for channel in asyncore.socket_map.values():
            if channel.bytes_in > self.max_size:
                channel.close() # too much data
                try:
                    channel.consumer.http(
                        0, channel, ("HTTPManager", "too much data", None)
                        )
                except:
                    pass
            if channel.timestamp and now - channel.timestamp > self.max_time:
                channel.close() # too slow
                try:
                    channel.consumer.http(
                        0, channel, ("HTTPManager", "timeout", None)
                        )
                except:
                    pass
        # activate up to max_connections channels
        while self.queue and len(asyncore.socket_map) < self.max_connections:
            http_client.do_request(*self.queue.pop(0))
        # keep the network running
        asyncore.poll(timeout)
        # return non-zero if we should keep on polling
        return len(self.queue) or len(asyncore.socket_map)
