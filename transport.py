# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.errors import (NoSuchFile, NotBranchError, TransportNotPossible, 
                           FileExists)
from bzrlib.trace import mutter
from bzrlib.transport import Transport
import bzrlib.urlutils as urlutils

from svn.core import SubversionException, Pool
import svn.ra
import svn.core
import svn.client

from errors import convert_svn_error

svn_config = svn.core.svn_config_get_config(None)


def need_lock(unbound):
    def locked(self, *args, **kwargs):
        self.lock()
        try:
            return unbound(self, *args, **kwargs)
        finally:
            self.unlock()
    locked.__doc__ = unbound.__doc__
    locked.__name__ = unbound.__name__
    return locked


def _create_auth_baton(pool):
    """Create a Subversion authentication baton. """
    # Give the client context baton a suite of authentication
    # providers.h
    providers = [
        svn.client.get_simple_provider(pool),
        svn.client.get_username_provider(pool),
        svn.client.get_ssl_client_cert_file_provider(pool),
        svn.client.get_ssl_client_cert_pw_file_provider(pool),
        svn.client.get_ssl_server_trust_file_provider(pool),
        ]
    return svn.core.svn_auth_open(providers, pool)


# Don't run any tests on SvnTransport as it is not intended to be 
# a full implementation of Transport
def get_test_permutations():
    return []


def get_svn_ra_transport(bzr_transport):
    """Obtain corresponding SvnRaTransport for a stock Bazaar transport."""
    if isinstance(bzr_transport, SvnRaTransport):
        return bzr_transport

    return SvnRaTransport(bzr_transport.base)


def bzr_to_svn_url(url):
    """Convert a Bazaar URL to a URL understood by Subversion.

    This will possibly remove the svn+ prefix.
    """
    if (url.startswith("svn+http://") or 
        url.startswith("svn+file://") or
        url.startswith("svn+https://")):
        url = url[len("svn+"):] # Skip svn+

    # The SVN libraries don't like trailing slashes...
    return url.rstrip('/')


class SvnRaTransport(Transport):
    """Fake transport for Subversion-related namespaces.
    
    This implements just as much of Transport as is necessary 
    to fool Bazaar. """
    @convert_svn_error
    def __init__(self, url=""):
        self.pool = Pool()
        self.is_locked = False
        bzr_url = url
        self.svn_url = bzr_to_svn_url(url)
        Transport.__init__(self, bzr_url)

        self._client = svn.client.create_context(self.pool)
        self._client.auth_baton = _create_auth_baton(self.pool)
        self._client.config = svn_config

        try:
            mutter('opening SVN RA connection to %r' % self.svn_url)
            self._ra = svn.client.open_ra_session(self.svn_url.encode('utf8'), 
                    self._client, self.pool)
        except SubversionException, (_, num):
            if num in (svn.core.SVN_ERR_RA_ILLEGAL_URL, \
                       svn.core.SVN_ERR_RA_LOCAL_REPOS_OPEN_FAILED, \
                       svn.core.SVN_ERR_BAD_URL):
                raise NotBranchError(path=url)
            raise

    class Reporter:
        def __init__(self, (reporter, report_baton)):
            self._reporter = reporter
            self._baton = report_baton

        def set_path(self, path, revnum, start_empty, lock_token, pool=None):
            svn.ra.reporter2_invoke_set_path(self._reporter, self._baton, 
                        path, revnum, start_empty, lock_token, pool)

        def delete_path(self, path, pool=None):
            svn.ra.reporter2_invoke_delete_path(self._reporter, self._baton,
                    path, pool)

        def link_path(self, path, url, revision, start_empty, lock_token, 
                      pool=None):
            svn.ra.reporter2_invoke_link_path(self._reporter, self._baton,
                    path, url, revision, start_empty, lock_token,
                    pool)

        def finish_report(self, pool=None):
            svn.ra.reporter2_invoke_finish_report(self._reporter, 
                    self._baton, pool)

        def abort_report(self, pool=None):
            svn.ra.reporter2_invoke_abort_report(self._reporter, 
                    self._baton, pool)

    def lock(self):
        assert (not self.is_locked)
        self.is_locked = True

    def unlock(self):
        assert self.is_locked
        self.is_locked = False

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

    @need_lock
    @convert_svn_error
    def get_uuid(self):
        mutter('svn get-uuid')
        return svn.ra.get_uuid(self._ra)

    @need_lock
    @convert_svn_error
    def get_repos_root(self):
        mutter("svn get-repos-root")
        return svn.ra.get_repos_root(self._ra)

    @need_lock
    @convert_svn_error
    def get_latest_revnum(self):
        mutter("svn get-latest-revnum")
        return svn.ra.get_latest_revnum(self._ra)

    @need_lock
    @convert_svn_error
    def do_switch(self, switch_rev, switch_target, recurse, switch_url, *args, **kwargs):
        mutter('svn switch -r %d %r -> %r' % (switch_rev, switch_target, switch_url))
        return self.Reporter(svn.ra.do_switch(self._ra, switch_rev, switch_target, recurse, switch_url, *args, **kwargs))

    @need_lock
    @convert_svn_error
    def get_log(self, path, from_revnum, to_revnum, *args, **kwargs):
        mutter('svn log %r:%r %r' % (from_revnum, to_revnum, path))
        return svn.ra.get_log(self._ra, [path], from_revnum, to_revnum, *args, **kwargs)

    @need_lock
    @convert_svn_error
    def reparent(self, url):
        url = url.rstrip("/")
        if url == self.svn_url:
            return
        self.base = url
        self.svn_url = url
        if hasattr(svn.ra, 'reparent'):
            mutter('svn reparent %r' % url)
            svn.ra.reparent(self._ra, url, self.pool)
        else:
            self._ra = svn.client.open_ra_session(self.svn_url.encode('utf8'), 
                    self._client, self.pool)
    @need_lock
    @convert_svn_error
    def get_dir(self, path, revnum, pool=None, kind=False):
        mutter("svn ls -r %d '%r'" % (revnum, path))
        path = path.rstrip("/")
        # ra_dav backends fail with strange errors if the path starts with a 
        # slash while other backends don't.
        assert len(path) == 0 or path[0] != "/"
        if hasattr(svn.ra, 'get_dir2'):
            fields = 0
            if kind:
                fields += svn.core.SVN_DIRENT_KIND
            return svn.ra.get_dir2(self._ra, path, revnum, fields)
        else:
            return svn.ra.get_dir(self._ra, path, revnum)

    @convert_svn_error
    def list_dir(self, relpath):
        assert len(relpath) == 0 or relpath[0] != "/"
        if relpath == ".":
            relpath = ""
        try:
            (dirents, _, _) = self.get_dir(relpath.rstrip("/"), 
                                           self.get_latest_revnum())
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_FS_NOT_DIRECTORY:
                raise NoSuchFile(relpath)
            raise
        return dirents.keys()

    @need_lock
    @convert_svn_error
    def check_path(self, path, revnum, *args, **kwargs):
        assert len(path) == 0 or path[0] != "/"
        mutter("svn check_path -r%d %s" % (revnum, path))
        return svn.ra.check_path(self._ra, path, revnum, *args, **kwargs)

    @need_lock
    @convert_svn_error
    def mkdir(self, relpath, mode=None):
        path = "%s/%s" % (self.svn_url, relpath)
        try:
            svn.client.mkdir([path.encode("utf-8")], self._client)
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_FS_NOT_FOUND:
                raise NoSuchFile(path)
            if num == svn.core.SVN_ERR_FS_ALREADY_EXISTS:
                raise FileExists(path)
            raise

    @need_lock
    @convert_svn_error
    def do_update(self, revnum, path, *args, **kwargs):
        mutter('svn update -r %r %r' % (revnum, path))
        return self.Reporter(svn.ra.do_update(self._ra, revnum, path, *args, **kwargs))

    @need_lock
    @convert_svn_error
    def get_commit_editor(self, *args, **kwargs):
        return svn.ra.get_commit_editor(self._ra, *args, **kwargs)

    def listable(self):
        """See Transport.listable().
        """
        return True

    # There is no real way to do locking directly on the transport 
    # nor is there a need to as the remote server will take care of 
    # locking
    class PhonyLock:
        def unlock(self):
            pass

    def lock_write(self, relpath):
        """See Transport.lock_write()."""
        return self.PhonyLock()

    def lock_read(self, relpath):
        """See Transport.lock_read()."""
        return self.PhonyLock()

    def clone(self, offset=None):
        """See Transport.clone()."""
        if offset is None:
            return SvnRaTransport(self.base)

        return SvnRaTransport(urlutils.join(self.base, offset))
