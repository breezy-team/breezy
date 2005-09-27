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
import os
import urllib2
import urlparse

from bzrlib.errors import BzrError, BzrCheckError
from bzrlib.branch import Branch, LocalBranch, BZR_BRANCH_FORMAT_5
from bzrlib.trace import mutter
from bzrlib.xml5 import serializer_v5

# velocitynet.com.au transparently proxies connections and thereby
# breaks keep-alive -- sucks!


ENABLE_URLGRABBER = False

from bzrlib.errors import BzrError, NoSuchRevision

class GetFailed(BzrError):
    def __init__(self, url, status):
        BzrError.__init__(self, "Get %s failed with status %s" % (url, status))
        self.url = url
        self.status = status

if ENABLE_URLGRABBER:
    import util.urlgrabber
    import util.urlgrabber.keepalive
    util.urlgrabber.keepalive.DEBUG = 0
    def get_url(path, compressed=False):
        try:
            url = path
            if compressed:
                url += '.gz'
            mutter("grab url %s" % url)
            url_f = util.urlgrabber.urlopen(url, keepalive=1, close_connection=0)
            if url_f.status != 200:
                raise GetFailed(url, url_f.status)
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
            fmt_url = url + '/.bzr/branch-format'
            ff = get_url(fmt_url)
            fmt = ff.read()
            ff.close()

            if fmt != BZR_BRANCH_FORMAT_5:
                raise BzrError("sorry, branch format %r not supported at url %s"
                               % (fmt, url))
            
            return url
        except urllib2.URLError:
            pass

        scheme, host, path = list(urlparse.urlparse(url))[:3]
        # discard params, query, fragment
        
        # strip off one component of the path component
        idx = path.rfind('/')
        if idx == -1 or path == '/':
            raise BzrError('no branch root found for URL %s'
                           ' or enclosing directories'
                           % orig_url)
        path = path[:idx]
        url = urlparse.urlunparse((scheme, host, path, '', '', ''))
        


class RemoteBranch(LocalBranch):
    def __init__(self, baseurl, find_root=True):
        """Create new proxy for a remote branch."""
        if find_root:
            self.base = _find_remote_root(baseurl)
        else:
            self.base = baseurl
            self._check_format()

        self.inventory_store = RemoteStore(baseurl + '/.bzr/inventory-store/')
        self.text_store = RemoteStore(baseurl + '/.bzr/text-store/')
        self.revision_store = RemoteStore(baseurl + '/.bzr/revision-store/')

    def __str__(self):
        b = getattr(self, 'baseurl', 'undefined')
        return '%s(%r)' % (self.__class__.__name__, b)

    __repr__ = __str__

    def setup_caching(self, cache_root):
        """Set up cached stores located under cache_root"""
        from bzrlib.meta_store import CachedStore
        for store_name in ('inventory_store', 'text_store', 'revision_store'):
            if not isinstance(getattr(self, store_name), CachedStore):
                cache_path = os.path.join(cache_root, store_name)
                os.mkdir(cache_path)
                new_store = CachedStore(getattr(self, store_name), cache_path)
                setattr(self, store_name, new_store)

    def controlfile(self, filename, mode):
        if mode not in ('rb', 'rt', 'r'):
            raise BzrError("file mode %r not supported for remote branches" % mode)
        return get_url(self.base + '/.bzr/' + filename, False)


    def lock_read(self):
        # no locking for remote branches yet
        pass

    def lock_write(self):
        from errors import LockError
        raise LockError("write lock not supported for remote branch %s"
                        % self.base)

    def unlock(self):
        pass
    

    def relpath(self, path):
        if not path.startswith(self.base):
            raise BzrError('path %r is not under base URL %r'
                           % (path, self.base))
        pl = len(self.base)
        return path[pl:].lstrip('/')


    def get_revision(self, revision_id):
        try:
            revf = self.revision_store[revision_id]
        except KeyError:
            raise NoSuchRevision(self, revision_id)
        r = serializer_v5.read_revision(revf)
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
        try:
            return get_url(p, compressed=True)
        except urllib2.URLError:
            pass
        try:
            return get_url(p, compressed=False)
        except urllib2.URLError:
            raise KeyError(fileid)
    

    
