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


"""Proxy object for access to remote branches.

At the moment remote branches are only for HTTP and only for read
access.
"""


import gzip
from cStringIO import StringIO
import urllib2

from errors import BzrError, BzrCheckError
from branch import Branch, BZR_BRANCH_FORMAT
from trace import mutter

# velocitynet.com.au transparently proxies connections and thereby
# breaks keep-alive -- sucks!


ENABLE_URLGRABBER = True


if ENABLE_URLGRABBER:
    import urlgrabber
    import urlgrabber.keepalive
    urlgrabber.keepalive.DEBUG = 0
    def get_url(path, compressed=False):
        try:
            url = path
            if compressed:
                url += '.gz'
            mutter("grab url %s" % url)
            url_f = urlgrabber.urlopen(url, keepalive=1, close_connection=0)
            if not compressed:
                return url_f
            else:
                return gzip.GzipFile(fileobj=StringIO(url_f.read()))
        except urllib2.URLError, e:
            raise BzrError("remote fetch failed: %r: %s" % (url, e))
else:
    def get_url(url, compressed=False):
        import urllib2
        if compressed:
            url += '.gz'
        mutter("get_url %s" % url)
        url_f = urllib2.urlopen(url)
        if compressed:
            return gzip.GzipFile(fileobj=StringIO(url_f.read()))
        else:
            return url_f



def _find_remote_root(url):
    """Return the prefix URL that corresponds to the branch root."""
    orig_url = url
    while True:
        try:
            ff = get_url(url + '/.bzr/branch-format')

            fmt = ff.read()
            ff.close()

            fmt = fmt.rstrip('\r\n')
            if fmt != BZR_BRANCH_FORMAT.rstrip('\r\n'):
                raise BzrError("sorry, branch format %r not supported at url %s"
                               % (fmt, url))
            
            return url
        except urllib2.URLError:
            pass

        try:
            idx = url.rindex('/')
        except ValueError:
            raise BzrError('no branch root found for URL %s' % orig_url)

        url = url[:idx]        
        


class RemoteBranch(Branch):
    def __init__(self, baseurl, find_root=True, lock_mode='r'):
        """Create new proxy for a remote branch."""
        if lock_mode not in ('', 'r'):
            raise BzrError('lock mode %r is not supported for remote branches'
                           % lock_mode)

        if find_root:
            self.baseurl = _find_remote_root(baseurl)
        else:
            self.baseurl = baseurl
            self._check_format()

        self.inventory_store = RemoteStore(baseurl + '/.bzr/inventory-store/')
        self.text_store = RemoteStore(baseurl + '/.bzr/text-store/')

    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self.baseurl)

    __repr__ = __str__

    def controlfile(self, filename, mode):
        if mode not in ('rb', 'rt', 'r'):
            raise BzrError("file mode %r not supported for remote branches" % mode)
        return get_url(self.baseurl + '/.bzr/' + filename, False)

    def _need_readlock(self):
        # remote branch always safe for read
        pass

    def _need_writelock(self):
        raise BzrError("cannot get write lock on HTTP remote branch")

    def relpath(self, path):
        if not path.startswith(self.baseurl):
            raise BzrError('path %r is not under base URL %r'
                           % (path, self.baseurl))
        pl = len(self.baseurl)
        return path[pl:].lstrip('/')

    def get_revision(self, revision_id):
        from revision import Revision
        revf = get_url(self.baseurl + '/.bzr/revision-store/' + revision_id,
                       True)
        r = Revision.read_xml(revf)
        if r.revision_id != revision_id:
            raise BzrCheckError('revision stored as {%s} actually contains {%s}'
                                % (revision_id, r.revision_id))
        return r


class RemoteStore(object):
    def __init__(self, baseurl):
        self._baseurl = baseurl
        

    def _path(self, name):
        if '/' in name:
            raise ValueError('invalid store id', name)
        return self._baseurl + '/' + name
        
    def __getitem__(self, fileid):
        p = self._path(fileid)
        return get_url(p, compressed=True)
    

def simple_walk():
    """For experimental purposes, traverse many parts of a remote branch"""
    from revision import Revision
    from branch import Branch
    from inventory import Inventory

    got_invs = {}
    got_texts = {}

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
                got_texts[text_id] = True

            got_invs.add[inv_id] = True

        print '----'


def try_me():
    BASE_URL = 'http://bazaar-ng.org/bzr/bzr.dev/'
    b = RemoteBranch(BASE_URL)
    ## print '\n'.join(b.revision_history())
    from log import show_log
    show_log(b)


if __name__ == '__main__':
    try_me()
    
