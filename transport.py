# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Simple transport for accessing Subversion smart servers."""

from bzrlib import debug, urlutils
from bzrlib.errors import (NoSuchFile, NotBranchError, TransportNotPossible, 
                           FileExists, NotLocalUrl, InvalidURL)
from bzrlib.trace import mutter
from bzrlib.transport import Transport

from svn.core import Pool
import svn.core
import svn.client

from bzrlib.plugins.svn.core import SubversionException, get_config
from bzrlib.plugins.svn.errors import convert_svn_error, NoSvnRepositoryPresent, ERR_BAD_URL, ERR_RA_SVN_REPOS_NOT_FOUND, ERR_FS_ALREADY_EXISTS, ERR_FS_NOT_FOUND, ERR_FS_NOT_DIRECTORY
from bzrlib.plugins.svn.ra import DIRENT_KIND, RemoteAccess
import urlparse
import urllib

svn_config = get_config(None)

def get_client_string():
    """Return a string that can be send as part of the User Agent string."""
    return "bzr%s+bzr-svn%s" % (bzrlib.__version__, bzrlib.plugins.svn.__version__)

 
# Don't run any tests on SvnTransport as it is not intended to be 
# a full implementation of Transport
def get_test_permutations():
    return []


def get_svn_ra_transport(bzr_transport):
    """Obtain corresponding SvnRaTransport for a stock Bazaar transport."""
    if isinstance(bzr_transport, SvnRaTransport):
        return bzr_transport

    return SvnRaTransport(bzr_transport.base)


def _url_unescape_uri(url):
    (scheme, netloc, path, query, fragment) = urlparse.urlsplit(url)
    path = urllib.unquote(path)
    return urlparse.urlunsplit((scheme, netloc, path, query, fragment))


def bzr_to_svn_url(url):
    """Convert a Bazaar URL to a URL understood by Subversion.

    This will possibly remove the svn+ prefix.
    """
    if (url.startswith("svn+http://") or 
        url.startswith("svn+file://") or
        url.startswith("svn+https://")):
        url = url[len("svn+"):] # Skip svn+

    if url.startswith("http"):
        # Without this, URLs with + in them break
        url = _url_unescape_uri(url)

    # The SVN libraries don't like trailing slashes...
    url = url.rstrip('/')

    return url


class ConnectionPool(object):
    """Collection of connections to a Subversion repository."""
    def __init__(self):
        self.connections = set()

    def get(self, url):
        # Check if there is an existing connection we can use
        for c in self.connections:
            assert not c.is_busy(), "busy connection in pool"
            if c.url == url:
                self.connections.remove(c)
                return c
        # Nothing available? Just pick an existing one and reparent:
        if len(self.connections) == 0:
            return RemoteAccess(url)
        c = self.connections.pop()
        try:
            c.reparent(url)
            return c
        except NotImplementedError:
            self.connections.add(c)
            return RemoteAccess(url)
        except:
            self.connections.add(c)
            raise

    def add(self, connection):
        assert not connection.is_busy(), "adding busy connection in pool"
        self.connections.add(connection)
    

class SvnRaTransport(Transport):
    """Fake transport for Subversion-related namespaces.
    
    This implements just as much of Transport as is necessary 
    to fool Bazaar. """
    @convert_svn_error
    def __init__(self, url="", _backing_url=None, pool=None):
        self.pool = Pool()
        bzr_url = url
        self.svn_url = bzr_to_svn_url(url)
        # _backing_url is an evil hack so the root directory of a repository 
        # can be accessed on some HTTP repositories. 
        if _backing_url is None:
            _backing_url = self.svn_url
        self._backing_url = _backing_url.rstrip("/")
        Transport.__init__(self, bzr_url)

        if pool is None:
            self.connections = ConnectionPool()

            # Make sure that the URL is valid by connecting to it.
            self.connections.add(self.connections.get(self._backing_url))
        else:
            self.connections = pool

        from bzrlib.plugins.svn import lazy_check_versions
        lazy_check_versions()

    def get_connection(self):
        return self.connections.get(self._backing_url)

    def add_connection(self, conn):
        self.connections.add(conn)

    def has(self, relpath):
        """See Transport.has()."""
        # TODO: Raise TransportNotPossible here instead and 
        # catch it in bzrdir.py
        return False

    def get(self, relpath):
        """See Transport.get()."""
        # TODO: Raise TransportNotPossible here instead and 
        # catch it in bzrdir.py
        raise NoSuchFile(path=relpath)

    def stat(self, relpath):
        """See Transport.stat()."""
        raise TransportNotPossible('stat not supported on Subversion')

    def get_uuid(self):
        conn = self.get_connection()
        try:
            return conn.get_uuid()
        finally:
            self.add_connection(conn)

    def get_repos_root(self):
        root = self.get_svn_repos_root()
        if (self.base.startswith("svn+http:") or 
            self.base.startswith("svn+https:")):
            return "svn+%s" % root
        return root

    def get_svn_repos_root(self):
        conn = self.get_connection()
        try:
            return conn.get_repos_root()
        finally:
            self.add_connection(conn)

    def get_latest_revnum(self):
        conn = self.get_connection()
        try:
            return conn.get_latest_revnum()
        finally:
            self.add_connection(conn)

    def do_switch(self, switch_rev, recurse, switch_url, editor, pool=None):
        conn = self._open_real_transport()
        conn.set_unbusy_handler(lambda: self.add_connection(conn))
        return conn.do_switch(switch_rev, recurse, switch_url, editor, pool)

    def iter_log(self, paths, from_revnum, to_revnum, limit, discover_changed_paths, 
                 strict_node_history, revprops):

        assert paths is None or isinstance(paths, list)
        assert paths is None or all([isinstance(x, str) for x in paths])
        assert isinstance(from_revnum, int) and isinstance(to_revnum, int)
        assert isinstance(limit, int)
        from threading import Thread, Semaphore

        class logfetcher(Thread):
            def __init__(self, transport, **kwargs):
                Thread.__init__(self)
                self.setDaemon(True)
                self.transport = transport
                self.kwargs = kwargs
                self.pending = []
                self.conn = None
                self.semaphore = Semaphore(0)

            def next(self):
                self.semaphore.acquire()
                ret = self.pending.pop(0)
                if ret is None:
                    self.transport.add_connection(self.conn)
                elif isinstance(ret, Exception):
                    self.transport.add_connection(self.conn)
                    raise ret
                return ret

            def run(self):
                assert self.conn is None, "already running"
                def rcvr(log_entry, pool):
                    self.pending.append((log_entry.changed_paths, log_entry.revision, log_entry.revprops))
                    self.semaphore.release()
                self.conn = self.transport.get_connection()
                try:
                    self.conn.get_log(rcvr=rcvr, **self.kwargs)
                    self.pending.append(None)
                except Exception, e:
                    self.pending.append(e)
                self.semaphore.release()

        if paths is None:
            newpaths = None
        else:
            newpaths = [self._request_path(path) for path in paths]
        
        fetcher = logfetcher(self, paths=newpaths, from_revnum=from_revnum, to_revnum=to_revnum, limit=limit, discover_changed_paths=discover_changed_paths, strict_node_history=strict_node_history, revprops=revprops)
        fetcher.start()
        return iter(fetcher.next, None)

    def get_log(self, paths, from_revnum, to_revnum, limit, discover_changed_paths, 
                strict_node_history, revprops, rcvr, pool=None):
        assert paths is None or isinstance(paths, list), "Invalid paths"
        assert paths is None or all([isinstance(x, str) for x in paths])

        if paths is None:
            newpaths = None
        else:
            newpaths = [self._request_path(path) for path in paths]

        conn = self.get_connection()
        try:
            return conn.get_log(newpaths, 
                    from_revnum, to_revnum,
                    limit, discover_changed_paths, strict_node_history, 
                    revprops, rcvr, pool)
        finally:
            self.add_connection(conn)

    def _open_real_transport(self):
        if self._backing_url != self.svn_url:
            return self.connections.get(self.svn_url)
        return self.get_connection()

    def change_rev_prop(self, revnum, name, value, pool=None):
        conn = self.get_connection()
        try:
            return conn.change_rev_prop(revnum, name, value, pool)
        finally:
            self.add_connection(conn)

    def get_dir(self, path, revnum, pool=None, kind=False):
        path = self._request_path(path)
        conn = self.get_connection()
        try:
            return conn.get_dir(path, revnum, pool, kind)
        finally:
            self.add_connection(conn)

    def mutter(self, text, *args):
        if 'transport' in debug.debug_flags:
            mutter(text, *args)

    def _request_path(self, relpath):
        if self._backing_url == self.svn_url:
            return relpath.strip("/")
        newsvnurl = urlutils.join(self.svn_url, relpath)
        if newsvnurl == self._backing_url:
            return ""
        newrelpath = urlutils.relative_url(self._backing_url+"/", newsvnurl+"/").strip("/")
        self.mutter('request path %r -> %r', relpath, newrelpath)
        return newrelpath

    def list_dir(self, relpath):
        assert len(relpath) == 0 or relpath[0] != "/"
        if relpath == ".":
            relpath = ""
        try:
            (dirents, _, _) = self.get_dir(relpath, self.get_latest_revnum())
        except SubversionException, (msg, num):
            if num == ERR_FS_NOT_DIRECTORY:
                raise NoSuchFile(relpath)
            raise
        return dirents.keys()

    def check_path(self, path, revnum):
        path = self._request_path(path)
        conn = self.get_connection()
        try:
            return conn.check_path(path, revnum)
        finally:
            self.add_connection(conn)

    def mkdir(self, relpath, mode=None):
        conn = self.get_connection()
        try:
            return conn.mkdir(relpath, mode)
        finally:
            self.add_connection(conn)

    def replay(self, revision, low_water_mark, send_deltas, editor, pool=None):
        conn = self._open_real_transport()
        try:
            return conn.replay(revision, low_water_mark, 
                                             send_deltas, editor, pool)
        finally:
            self.add_connection(conn)

    def do_update(self, revnum, recurse, editor, pool=None):
        conn = self._open_real_transport()
        conn.set_unbusy_handler(lambda: self.add_connection(conn))
        return conn.do_update(revnum, recurse, editor, pool)

    def has_capability(self, cap):
        conn = self.get_connection()
        try:
            return conn.has_capability(cap)
        finally:
            self.add_connection(conn)

    def revprop_list(self, revnum, pool=None):
        conn = self.get_connection()
        try:
            return conn.revprop_list(revnum, pool)
        finally:
            self.add_connection(conn)

    def get_commit_editor(self, revprops, done_cb, lock_token, keep_locks):
        conn = self._open_real_transport()
        conn.set_unbusy_handler(lambda: self.add_connection(conn))
        return conn.get_commit_editor(revprops, done_cb,
                                     lock_token, keep_locks)

    def listable(self):
        """See Transport.listable().
        """
        return True

    # There is no real way to do locking directly on the transport 
    # nor is there a need to as the remote server will take care of 
    # locking
    class PhonyLock(object):
        def unlock(self):
            pass

    def lock_read(self, relpath):
        """See Transport.lock_read()."""
        return self.PhonyLock()

    def lock_write(self, path_revs, comment=None, steal_lock=False):
        return self.PhonyLock() # FIXME

    def _is_http_transport(self):
        return (self.svn_url.startswith("http://") or 
                self.svn_url.startswith("https://"))

    def clone_root(self):
        if self._is_http_transport():
            return SvnRaTransport(self.get_repos_root(), 
                                  bzr_to_svn_url(self.base),
                                  pool=self.connections)
        return SvnRaTransport(self.get_repos_root(),
                              pool=self.connections)

    def clone(self, offset=None):
        """See Transport.clone()."""
        if offset is None:
            return SvnRaTransport(self.base, pool=self.connections)

        return SvnRaTransport(urlutils.join(self.base, offset), pool=self.connections)

    def local_abspath(self, relpath):
        """See Transport.local_abspath()."""
        absurl = self.abspath(relpath)
        if self.base.startswith("file:///"):
            return urlutils.local_path_from_url(absurl)
        raise NotLocalUrl(absurl)

    def abspath(self, relpath):
        """See Transport.abspath()."""
        return urlutils.join(self.base, relpath)
