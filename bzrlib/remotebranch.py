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
    def __init__(self, baseurl, find_root=True):
        """Create new proxy for a remote branch."""
        if find_root:
            self.baseurl = _find_remote_root(baseurl)
        else:
            self.baseurl = baseurl
            self._check_format()

        self.inventory_store = RemoteStore(baseurl + '/.bzr/inventory-store/')
        self.text_store = RemoteStore(baseurl + '/.bzr/text-store/')
        self.revision_store = RemoteStore(baseurl + '/.bzr/revision-store/')

    def __str__(self):
        b = getattr(self, 'baseurl', 'undefined')
        return '%s(%r)' % (self.__class__.__name__, b)

    __repr__ = __str__

    def controlfile(self, filename, mode):
        if mode not in ('rb', 'rt', 'r'):
            raise BzrError("file mode %r not supported for remote branches" % mode)
        return get_url(self.baseurl + '/.bzr/' + filename, False)


    def lock_read(self):
        # no locking for remote branches yet
        pass

    def lock_write(self):
        from errors import LockError
        raise LockError("write lock not supported for remote branch %s"
                        % self.baseurl)

    def unlock(self):
        pass
    

    def relpath(self, path):
        if not path.startswith(self.baseurl):
            raise BzrError('path %r is not under base URL %r'
                           % (path, self.baseurl))
        pl = len(self.baseurl)
        return path[pl:].lstrip('/')


    def get_revision(self, revision_id):
        from bzrlib.revision import Revision
        from bzrlib.xml import unpack_xml
        try:
            revf = self.revision_store[revision_id]
        except KeyError:
            raise NoSuchRevision(self, revision_id)
        r = unpack_xml(Revision, revf)
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
        except:
            raise KeyError(fileid)
    

    
