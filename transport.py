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

import bzrlib
from bzrlib import debug, urlutils
from bzrlib.errors import (NoSuchFile, TransportNotPossible, 
                           FileExists, NotLocalUrl, InvalidURL)
from bzrlib.trace import mutter, warning
from bzrlib.transport import Transport

import bzrlib.plugins.svn
from bzrlib.plugins.svn import core, properties, ra
from bzrlib.plugins.svn import properties
from bzrlib.plugins.svn.auth import create_auth_baton
from bzrlib.plugins.svn.client import get_config
from bzrlib.plugins.svn.core import SubversionException
from bzrlib.plugins.svn.errors import convert_svn_error, NoSvnRepositoryPresent, ERR_BAD_URL, ERR_RA_SVN_REPOS_NOT_FOUND, ERR_FS_ALREADY_EXISTS, ERR_FS_NOT_FOUND, ERR_FS_NOT_DIRECTORY, ERR_RA_DAV_RELOCATED, RedirectRequested
from bzrlib.plugins.svn.ra import DIRENT_KIND, RemoteAccess
import urlparse
import urllib

svn_config = get_config()

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

    ra_transport = getattr(bzr_transport, "_svn_ra", None)
    if ra_transport is not None:
        return ra_transport

    # Save _svn_ra transport here so we don't have to connect again next time
    # we try to use bzr svn on this transport
    ra_transport = SvnRaTransport(bzr_transport.base)
    bzr_transport._svn_ra = ra_transport
    return ra_transport


def _url_unescape_uri(url):
    (scheme, netloc, path, query, fragment) = urlparse.urlsplit(url)
    path = urllib.unquote(path)
    return urlparse.urlunsplit((scheme, netloc, path, query, fragment))


svnplus_warning_showed = False

def warn_svnplus(url):
    global svnplus_warning_showed
    if not svnplus_warning_showed:
        warning("The svn+ syntax is deprecated, use %s instead.", url)
        svnplus_warning_showed = True


def bzr_to_svn_url(url):
    """Convert a Bazaar URL to a URL understood by Subversion.

    This will possibly remove the svn+ prefix.
    """
    if (url.startswith("svn+http://") or 
        url.startswith("svn+file://") or
        url.startswith("svn+https://")):
        url = url[len("svn+"):] # Skip svn+
        warn_svnplus(url)

    if url.startswith("http"):
        # Without this, URLs with + in them break
        url = _url_unescape_uri(url)

    # The SVN libraries don't like trailing slashes...
    url = url.rstrip('/')

    return url


def Connection(url):
    try:
        mutter('opening SVN RA connection to %r' % url)
        ret = ra.RemoteAccess(url.encode('utf8'), 
                auth=create_auth_baton(url),
                client_string_func=get_client_string)
    except SubversionException, (msg, num):
        if num in (ERR_RA_SVN_REPOS_NOT_FOUND,):
            raise NoSvnRepositoryPresent(url=url)
        if num == ERR_BAD_URL:
            raise InvalidURL(url)
        if num == ERR_RA_DAV_RELOCATED:
            raise RedirectRequested(url, msg.split("'")[1], is_permanent=True)
        raise

    from bzrlib.plugins.svn import lazy_check_versions
    lazy_check_versions()

    return ret


class ConnectionPool(object):
    """Collection of connections to a Subversion repository."""
    def __init__(self):
        self.connections = set()

    def get(self, url):
        # Check if there is an existing connection we can use
        for c in self.connections:
            assert not c.busy, "busy connection in pool"
            if c.url == url:
                self.connections.remove(c)
                return c
        # Nothing available? Just pick an existing one and reparent:
        if len(self.connections) == 0:
            return Connection(url)
        c = self.connections.pop()
        try:
            c.reparent(url)
            return c
        except NotImplementedError:
            self.connections.add(c)
            return Connection(url)
        except:
            self.connections.add(c)
            raise

    def add(self, connection):
        assert not connection.busy, "adding busy connection in pool"
        self.connections.add(connection)
    

class SvnRaTransport(Transport):
    """Fake transport for Subversion-related namespaces.
    
    This implements just as much of Transport as is necessary 
    to fool Bazaar. """
    @convert_svn_error
    def __init__(self, url="", _backing_url=None, pool=None, _uuid=None, _repos_root=None):
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

        self._repos_root = _repos_root
        self._uuid = _uuid
        self.capabilities = {}

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
        if self._uuid is None:
            conn = self.get_connection()
            self.mutter('svn get-uuid')
            try:
                return conn.get_uuid()
            finally:
                self.add_connection(conn)
        return self._uuid

    def get_repos_root(self):
        root = self.get_svn_repos_root()
        if (self.base.startswith("svn+http:") or 
            self.base.startswith("svn+https:")):
            return "svn+%s" % root
        return root

    def get_svn_repos_root(self):
        if self._repos_root is None:
            self.mutter('svn get-repos-root')
            conn = self.get_connection()
            try:
                self._repos_root = conn.get_repos_root()
            finally:
                self.add_connection(conn)
        return self._repos_root

    def get_latest_revnum(self):
        conn = self.get_connection()
        self.mutter('svn get-latest-revnum')
        try:
            return conn.get_latest_revnum()
        finally:
            self.add_connection(conn)

    def iter_log(self, paths, from_revnum, to_revnum, limit, discover_changed_paths, 
                 strict_node_history, include_merged_revisions, revprops):
        assert paths is None or isinstance(paths, list)
        assert isinstance(from_revnum, int) and isinstance(to_revnum, int)
        assert isinstance(limit, int)
        from threading import Thread, Semaphore

        class logfetcher(Thread):
            def __init__(self, transport, *args, **kwargs):
                Thread.__init__(self)
                self.setDaemon(True)
                self.transport = transport
                self.args = args
                self.kwargs = kwargs
                self.pending = []
                self.conn = self.transport.get_connection()
                self.semaphore = Semaphore(0)
                self.busy = False

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
                assert not self.busy, "already running"
                self.busy = True
                def rcvr(*args):
                    self.pending.append(args)
                    self.semaphore.release()
                try:
                    try:
                        self.conn.get_log(callback=rcvr, *self.args, **self.kwargs)
                        self.pending.append(None)
                    except Exception, e:
                        self.pending.append(e)
                finally:
                    self.pending.append(Exception("Some exception was not handled"))
                    self.semaphore.release()

        if paths is None:
            newpaths = None
        else:
            newpaths = [self._request_path(path) for path in paths]
        
        fetcher = logfetcher(self, paths=newpaths, start=from_revnum, end=to_revnum, limit=limit, discover_changed_paths=discover_changed_paths, strict_node_history=strict_node_history, include_merged_revisions=include_merged_revisions,revprops=revprops)
        fetcher.start()
        return iter(fetcher.next, None)

    def get_log(self, rcvr, paths, from_revnum, to_revnum, limit, discover_changed_paths, 
                strict_node_history, include_merged_revisions, revprops):
        assert paths is None or isinstance(paths, list), "Invalid paths"

        all_true = True
        for item in [isinstance(x, str) for x in paths]:
            if not item:
                all_true = False
                break
        
        assert paths is None or all_true

        self.mutter('svn log -r%d:%d %r' % (from_revnum, to_revnum, paths))

        if paths is None:
            newpaths = None
        else:
            newpaths = [self._request_path(path) for path in paths]

        conn = self.get_connection()
        try:
            return conn.get_log(rcvr, newpaths, 
                    from_revnum, to_revnum,
                    limit, discover_changed_paths, strict_node_history, 
                    include_merged_revisions,
                    revprops)
        finally:
            self.add_connection(conn)

    def _open_real_transport(self):
        if self._backing_url != self.svn_url:
            return self.connections.get(self.svn_url)
        return self.get_connection()

    def change_rev_prop(self, revnum, name, value):
        conn = self.get_connection()
        self.mutter('svn change-revprop -r%d %s=%s' % (revnum, name, value))
        try:
            return conn.change_rev_prop(revnum, name, value)
        finally:
            self.add_connection(conn)

    def get_dir(self, path, revnum, kind=False):
        path = self._request_path(path)
        conn = self.get_connection()
        self.mutter('svn get-dir -r%d %s' % (revnum, path))
        try:
            return conn.get_dir(path, revnum, kind)
        finally:
            self.add_connection(conn)

    def get_file(self, path, stream, revnum):
        path = self._request_path(path)
        conn = self.get_connection()
        self.mutter('svn get-file -r%d %s' % (revnum, path))
        try:
            return conn.get_file(path, stream, revnum)
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
        self.mutter('svn check-path -r%d %s' % (revnum, path))
        try:
            return conn.check_path(path, revnum)
        finally:
            self.add_connection(conn)

    @convert_svn_error
    def mkdir(self, relpath, message="Creating directory"):
        conn = self.get_connection()
        self.mutter('svn mkdir %s' % (relpath,))
        try:
            ce = conn.get_commit_editor({"svn:log": message})
            try:
                node = ce.open_root(-1)
                batons = relpath.split("/")
                toclose = [node]
                for i in range(len(batons)):
                    node = node.open_directory("/".join(batons[:i]), -1)
                    toclose.append(node)
                toclose.append(node.add_directory(relpath, None, -1))
                for c in reversed(toclose):
                    c.close()
                ce.close()
            except SubversionException, (msg, num):
                ce.abort()
                if num == ERR_FS_NOT_DIRECTORY:
                    raise NoSuchFile(msg)
                if num == ERR_FS_ALREADY_EXISTS:
                    raise FileExists(msg)
                raise
        finally:
            self.add_connection(conn)

    def has_capability(self, cap):
        if cap in self.capabilities:
            return self.capabilities[cap]
        conn = self.get_connection()
        self.mutter('svn has-capability %s' % (cap,))
        try:
            try:
                self.capabilities[cap] = conn.has_capability(cap)
            except NotImplementedError:
                self.capabilities[cap] = False # Assume the worst
            return self.capabilities[cap]
        finally:
            self.add_connection(conn)

    def revprop_list(self, revnum):
        conn = self.get_connection()
        self.mutter('svn revprop-list -r%d' % (revnum,))
        try:
            return conn.rev_proplist(revnum)
        finally:
            self.add_connection(conn)

    def get_locations(self, path, peg_revnum, revnums):
        conn = self.get_connection()
        self.mutter('svn get_locations -r%d %s (%r)' % (peg_revnum,path,revnums))
        try:
            return conn.get_locations(path, peg_revnum, revnums)
        finally:
            self.add_connection(conn)

    @convert_svn_error
    def get_commit_editor(self, revprops, done_cb=None, 
                          lock_token=None, keep_locks=False):
        conn = self._open_real_transport()
        self.mutter('svn get-commit-editor %r' % (revprops,))
        return conn.get_commit_editor(revprops, done_cb, lock_token, keep_locks)

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
        return False
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
            newurl = self.base
        else:
            newurl = urlutils.join(self.base, offset)

        return SvnRaTransport(newurl, pool=self.connections)

    def local_abspath(self, relpath):
        """See Transport.local_abspath()."""
        absurl = self.abspath(relpath)
        if self.base.startswith("file:///"):
            return urlutils.local_path_from_url(absurl)
        raise NotLocalUrl(absurl)

    def abspath(self, relpath):
        """See Transport.abspath()."""
        return urlutils.join(self.base, relpath)
