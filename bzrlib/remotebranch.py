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
from inventory import Inventory

# h = HTTPConnection('localhost:8000')
# h = HTTPConnection('bazaar-ng.org')

# velocitynet.com.au transparently proxies connections and thereby
# breaks keep-alive -- sucks!


import urlgrabber.keepalive
urlgrabber.keepalive.DEBUG = 2

import urlgrabber

prefix = 'http://localhost:8000'
# prefix = 'http://bazaar-ng.org/bzr/main/'

def get_url(path, compressed=False):
    try:
        url = prefix + path
        if compressed:
            url += '.gz'
        url_f = urlgrabber.urlopen(url, keepalive=1, close_connection=0)
        if not compressed:
            return url_f
        else:
            return gzip.GzipFile(fileobj=StringIO(url_f.read()))
    except urllib2.URLError, e:
        raise BzrError("remote fetch failed: %r: %s" % (url, e))


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
