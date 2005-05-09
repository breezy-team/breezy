#! /usr/bin/env python

# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


## XXX: This is pretty slow on high-latency connections because it
## doesn't keep the HTTP connection alive.  If you have a smart local
## proxy it may be much better.  Eventually I want to switch to
## urlgrabber which should use HTTP much more efficiently.


import urllib2, gzip, zlib
from sets import Set
from cStringIO import StringIO

from errors import BzrError
from revision import Revision
from branch import Branch
from inventory import Inventory

# h = HTTPConnection('localhost:8000')
# h = HTTPConnection('bazaar-ng.org')

# velocitynet.com.au transparently proxies connections and thereby
# breaks keep-alive -- sucks!


import urlgrabber.keepalive
urlgrabber.keepalive.DEBUG = 2

import urlgrabber

# prefix = 'http://localhost:8000'
BASE_URL = 'http://bazaar-ng.org/bzr/bzr.dev/'

def get_url(path, compressed=False):
    try:
        url = path
        if compressed:
            url += '.gz'
        url_f = urlgrabber.urlopen(url, keepalive=1, close_connection=0)
        if not compressed:
            return url_f
        else:
            return gzip.GzipFile(fileobj=StringIO(url_f.read()))
    except urllib2.URLError, e:
        raise BzrError("remote fetch failed: %r: %s" % (url, e))


class RemoteBranch(Branch):
    def __init__(self, baseurl):
        """Create new proxy for a remote branch."""
        self.baseurl = baseurl
        self._check_format()


    def controlfile(self, filename, mode):
        if mode not in ('rb', 'rt', 'r'):
            raise BzrError("file mode %r not supported for remote branches" % mode)
        return get_url(self.baseurl + '/.bzr/' + filename, False)

    def _need_readlock(self):
        # remote branch always safe for read
        pass

    def _need_writelock(self):
        raise BzrError("cannot get write lock on HTTP remote branch")
    


def simple_walk():
    got_invs = Set()
    got_texts = Set()

    print 'read history'
    history = get_url('/.bzr/revision-history').readlines()
    num_revs = len(history)
    for i, rev_id in enumerate(history):
        rev_id = rev_id.rstrip()
        print 'read revision %d/%d' % (i, num_revs)

        # python gzip needs a seekable file (!!) but the HTTP response
        # isn't, so we need to buffer it

        rev_f = get_url('/.bzr/revision-store/%s' % rev_id,
                        compressed=True)

        rev = Revision.read_xml(rev_f)
        print rev.message
        inv_id = rev.inventory_id
        if inv_id not in got_invs:
            print 'get inventory %s' % inv_id
            inv_f = get_url('/.bzr/inventory-store/%s' % inv_id,
                            compressed=True)
            inv = Inventory.read_xml(inv_f)
            print '%4d inventory entries' % len(inv)

            for path, ie in inv.iter_entries():
                text_id = ie.text_id
                if text_id == None:
                    continue
                if text_id in got_texts:
                    continue
                print '  fetch %s text {%s}' % (path, text_id)
                text_f = get_url('/.bzr/text-store/%s' % text_id,
                                 compressed=True)
                got_texts.add(text_id)

            got_invs.add(inv_id)

        print '----'


def try_me():
    b = RemoteBranch(BASE_URL)
    print '\n'.join(b.revision_history())


if __name__ == '__main__':
    try_me()
    
