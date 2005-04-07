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

from errors import BzrError
from revision import Revision
from cStringIO import StringIO

# h = HTTPConnection('localhost:8000')
# h = HTTPConnection('bazaar-ng.org')


prefix = 'http://bazaar-ng.org/bzr/main'

def get_url(path):
    try:
        url = prefix + path
        return urllib2.urlopen(url)
    except urllib2.URLError, e:
        raise BzrError("remote fetch failed: %r: %s" % (url, e))

print 'read history'
history = get_url('/.bzr/revision-history').read().split('\n')
for i, rev_id in enumerate(history):
    print 'read revision %d' % i
    comp_f = get_url('/.bzr/revision-store/%s.gz' % rev_id)
    comp_data = comp_f.read()

    # python gzip needs a seekable file (!!) but the HTTP response
    # isn't, so we need to buffer it
    
    uncomp_f = gzip.GzipFile(fileobj=StringIO(comp_data))

    rev = Revision.read_xml(uncomp_f)
    print rev.message
    print '----'
    
    
    


