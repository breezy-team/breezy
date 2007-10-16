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
"""Simple transport for accessing Subversion smart servers."""

from bzrlib import debug, urlutils
from bzrlib.errors import (NoSuchFile, NotBranchError, TransportNotPossible, 
                           FileExists, NotLocalUrl, InvalidURL)
from bzrlib.trace import mutter
from bzrlib.transport import Transport

from svn.core import SubversionException, Pool
import svn.ra
import svn.core
import svn.client

from errors import convert_svn_error, NoSvnRepositoryPresent

svn_config = svn.core.svn_config_get_config(None)


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


def create_svn_client(pool):
    client = svn.client.create_context(pool)
    client.auth_baton = _create_auth_baton(pool)
    client.config = svn_config
    return client


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


def needs_busy(unbound):
    """Decorator that marks a transport as busy before running a methd on it.
    """
    def convert(self, *args, **kwargs):
        self._mark_busy()
        ret = unbound(self, *args, **kwargs)
        self._unmark_busy()
        return ret

    convert.__doc__ = unbound.__doc__
    convert.__name__ = unbound.__name__
    return convert


class Editor:
    """Simple object wrapper around the Subversion delta editor interface."""
    def __init__(self, transport, (editor, editor_baton)):
        self.editor = editor
        self.editor_baton = editor_baton
        self.recent_baton = []
        self._transport = transport

    @convert_svn_error
    def open_root(self, base_revnum):
        assert self.recent_baton == [], "root already opened"
        baton = svn.delta.editor_invoke_open_root(self.editor, 
                self.editor_baton, base_revnum)
        self.recent_baton.append(baton)
        return baton

    @convert_svn_error
    def close_directory(self, baton, *args, **kwargs):
        assert self.recent_baton.pop() == baton, \
                "only most recently opened baton can be closed"
        svn.delta.editor_invoke_close_directory(self.editor, baton, *args, **kwargs)

    @convert_svn_error
    def close(self):
        assert self.recent_baton == []
        svn.delta.editor_invoke_close_edit(self.editor, self.editor_baton)
        self._transport._unmark_busy()

    @convert_svn_error
    def apply_textdelta(self, baton, *args, **kwargs):
        assert self.recent_baton[-1] == baton
        return svn.delta.editor_invoke_apply_textdelta(self.editor, baton,
                *args, **kwargs)

    @convert_svn_error
    def change_dir_prop(self, baton, name, value, pool=None):
        assert self.recent_baton[-1] == baton
        return svn.delta.editor_invoke_change_dir_prop(self.editor, baton, 
                                                       name, value, pool)

    @convert_svn_error
    def delete_entry(self, *args, **kwargs):
        return svn.delta.editor_invoke_delete_entry(self.editor, *args, **kwargs)

    @convert_svn_error
    def add_file(self, path, parent_baton, *args, **kwargs):
        assert self.recent_baton[-1] == parent_baton
        baton = svn.delta.editor_invoke_add_file(self.editor, path, 
            parent_baton, *args, **kwargs)
        self.recent_baton.append(baton)
        return baton

    @convert_svn_error
    def open_file(self, path, parent_baton, *args, **kwargs):
        assert self.recent_baton[-1] == parent_baton
        baton = svn.delta.editor_invoke_open_file(self.editor, path, 
                                                 parent_baton, *args, **kwargs)
        self.recent_baton.append(baton)
        return baton

    @convert_svn_error
    def change_file_prop(self, baton, name, value, pool=None):
        assert self.recent_baton[-1] == baton
        svn.delta.editor_invoke_change_file_prop(self.editor, baton, name, 
                                                 value, pool)

    @convert_svn_error
    def close_file(self, baton, *args, **kwargs):
        assert self.recent_baton.pop() == baton
        svn.delta.editor_invoke_close_file(self.editor, baton, *args, **kwargs)

    @convert_svn_error
    def add_directory(self, path, parent_baton, *args, **kwargs):
        assert self.recent_baton[-1] == parent_baton
        baton = svn.delta.editor_invoke_add_directory(self.editor, path, 
            parent_baton, *args, **kwargs)
        self.recent_baton.append(baton)
        return baton

    @convert_svn_error
    def open_directory(self, path, parent_baton, *args, **kwargs):
        assert self.recent_baton[-1] == parent_baton
        baton = svn.delta.editor_invoke_open_directory(self.editor, path, 
            parent_baton, *args, **kwargs)
        self.recent_baton.append(baton)
        return baton


class SvnRaTransport(Transport):
    """Fake transport for Subversion-related namespaces.
    
    This implements just as much of Transport as is necessary 
    to fool Bazaar. """
    @convert_svn_error
    def __init__(self, url="", _backing_url=None):
        self.pool = Pool()
        bzr_url = url
        self.svn_url = bzr_to_svn_url(url)
        self._root = None
        # _backing_url is an evil hack so the root directory of a repository 
        # can be accessed on some HTTP repositories. 
        if _backing_url is None:
            _backing_url = self.svn_url
        self._backing_url = _backing_url.rstrip("/")
        Transport.__init__(self, bzr_url)

        self._client = create_svn_client(self.pool)
        try:
            self.mutter('opening SVN RA connection to %r' % self._backing_url)
            self._ra = svn.client.open_ra_session(self._backing_url.encode('utf8'), 
                    self._client, self.pool)
        except SubversionException, (_, num):
            if num in (svn.core.SVN_ERR_RA_SVN_REPOS_NOT_FOUND,):
                raise NoSvnRepositoryPresent(url=url)
            if num == svn.core.SVN_ERR_BAD_URL:
                raise InvalidURL(url)
            raise

        from bzrlib.plugins.svn import lazy_check_versions
        lazy_check_versions()

        self._busy = False

    def _mark_busy(self):
        assert not self._busy
        self._busy = True

    def _unmark_busy(self):
        assert self._busy
        self._busy = False

    def mutter(self, text):
        if 'transport' in debug.debug_flags:
            mutter(text)

    class Reporter:
        def __init__(self, transport, (reporter, report_baton)):
            self._reporter = reporter
            self._baton = report_baton
            self._transport = transport

        @convert_svn_error
        def set_path(self, path, revnum, start_empty, lock_token, pool=None):
            svn.ra.reporter2_invoke_set_path(self._reporter, self._baton, 
                        path, revnum, start_empty, lock_token, pool)

        @convert_svn_error
        def delete_path(self, path, pool=None):
            svn.ra.reporter2_invoke_delete_path(self._reporter, self._baton,
                    path, pool)

        @convert_svn_error
        def link_path(self, path, url, revision, start_empty, lock_token, 
                      pool=None):
            svn.ra.reporter2_invoke_link_path(self._reporter, self._baton,
                    path, url, revision, start_empty, lock_token,
                    pool)

        @convert_svn_error
        def finish_report(self, pool=None):
            svn.ra.reporter2_invoke_finish_report(self._reporter, 
                    self._baton, pool)
            self._transport._unmark_busy()

        @convert_svn_error
        def abort_report(self, pool=None):
            svn.ra.reporter2_invoke_abort_report(self._reporter, 
                    self._baton, pool)
            self._transport._unmark_busy()

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

    @convert_svn_error
    @needs_busy
    def get_uuid(self):
        self.mutter('svn get-uuid')
        return svn.ra.get_uuid(self._ra)

    def get_repos_root(self):
        root = self.get_svn_repos_root()
        if (self.base.startswith("svn+http:") or 
            self.base.startswith("svn+https:")):
            return "svn+%s" % root
        return root

    @convert_svn_error
    @needs_busy
    def get_svn_repos_root(self):
        if self._root is None:
            self.mutter("svn get-repos-root")
            self._root = svn.ra.get_repos_root(self._ra)
        return self._root

    @convert_svn_error
    @needs_busy
    def get_latest_revnum(self):
        self.mutter("svn get-latest-revnum")
        return svn.ra.get_latest_revnum(self._ra)

    @convert_svn_error
    def do_switch(self, switch_rev, recurse, switch_url, *args, **kwargs):
        self._open_real_transport()
        self.mutter('svn switch -r %d -> %r' % (switch_rev, switch_url))
        self._mark_busy()
        return self.Reporter(self, svn.ra.do_switch(self._ra, switch_rev, "", 
                             recurse, switch_url, *args, **kwargs))

    @convert_svn_error
    @needs_busy
    def get_log(self, path, from_revnum, to_revnum, *args, **kwargs):
        self.mutter('svn log %r:%r %r' % (from_revnum, to_revnum, path))
        return svn.ra.get_log(self._ra, [self._request_path(path)], 
                              from_revnum, to_revnum, *args, **kwargs)

    def _open_real_transport(self):
        if self._backing_url != self.svn_url:
            self.reparent(self.base)
        assert self._backing_url == self.svn_url

    def reparent_root(self):
        if self._is_http_transport():
            self.svn_url = self.get_svn_repos_root()
            self.base = self.get_repos_root()
        else:
            self.reparent(self.get_repos_root())

    @convert_svn_error
    @needs_busy
    def reparent(self, url):
        url = url.rstrip("/")
        self.base = url
        self.svn_url = bzr_to_svn_url(url)
        if self.svn_url == self._backing_url:
            return
        if hasattr(svn.ra, 'reparent'):
            self.mutter('svn reparent %r' % url)
            svn.ra.reparent(self._ra, self.svn_url, self.pool)
        else:
            self.mutter('svn reparent (reconnect) %r' % url)
            self._ra = svn.client.open_ra_session(self.svn_url.encode('utf8'), 
                    self._client, self.pool)
        self._backing_url = self.svn_url

    @convert_svn_error
    @needs_busy
    def get_dir(self, path, revnum, pool=None, kind=False):
        self.mutter("svn ls -r %d '%r'" % (revnum, path))
        assert len(path) == 0 or path[0] != "/"
        path = self._request_path(path)
        # ra_dav backends fail with strange errors if the path starts with a 
        # slash while other backends don't.
        if hasattr(svn.ra, 'get_dir2'):
            fields = 0
            if kind:
                fields += svn.core.SVN_DIRENT_KIND
            return svn.ra.get_dir2(self._ra, path, revnum, fields)
        else:
            return svn.ra.get_dir(self._ra, path, revnum)

    def _request_path(self, relpath):
        if self._backing_url == self.svn_url:
            return relpath
        newrelpath = urlutils.join(
                urlutils.relative_url(self._backing_url+"/", self.svn_url+"/"),
                relpath).rstrip("/")
        self.mutter('request path %r -> %r' % (relpath, newrelpath))
        return newrelpath

    @convert_svn_error
    def list_dir(self, relpath):
        assert len(relpath) == 0 or relpath[0] != "/"
        if relpath == ".":
            relpath = ""
        try:
            (dirents, _, _) = self.get_dir(self._request_path(relpath),
                                           self.get_latest_revnum())
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_FS_NOT_DIRECTORY:
                raise NoSuchFile(relpath)
            raise
        return dirents.keys()

    @convert_svn_error
    @needs_busy
    def get_lock(self, path):
        return svn.ra.get_lock(self._ra, path)

    class SvnLock:
        def __init__(self, transport, tokens):
            self._tokens = tokens
            self._transport = transport

        def unlock(self):
            self.transport.unlock(self.locks)

    @convert_svn_error
    @needs_busy
    def unlock(self, locks, break_lock=False):
        def lock_cb(baton, path, do_lock, lock, ra_err, pool):
            pass
        return svn.ra.unlock(self._ra, locks, break_lock, lock_cb)

    @convert_svn_error
    @needs_busy
    def lock_write(self, path_revs, comment=None, steal_lock=False):
        return self.PhonyLock() # FIXME
        tokens = {}
        def lock_cb(baton, path, do_lock, lock, ra_err, pool):
            tokens[path] = lock
        svn.ra.lock(self._ra, path_revs, comment, steal_lock, lock_cb)
        return SvnLock(self, tokens)

    @convert_svn_error
    @needs_busy
    def check_path(self, path, revnum, *args, **kwargs):
        assert len(path) == 0 or path[0] != "/"
        path = self._request_path(path)
        self.mutter("svn check_path -r%d %s" % (revnum, path))
        return svn.ra.check_path(self._ra, path.encode('utf-8'), revnum, *args, **kwargs)

    @convert_svn_error
    @needs_busy
    def mkdir(self, relpath, mode=None):
        assert len(relpath) == 0 or relpath[0] != "/"
        path = urlutils.join(self.svn_url, relpath)
        try:
            svn.client.mkdir([path.encode("utf-8")], self._client)
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_FS_NOT_FOUND:
                raise NoSuchFile(path)
            if num == svn.core.SVN_ERR_FS_ALREADY_EXISTS:
                raise FileExists(path)
            raise

    @convert_svn_error
    def do_update(self, revnum, *args, **kwargs):
        self._open_real_transport()
        self.mutter('svn update -r %r' % revnum)
        self._mark_busy()
        return self.Reporter(self, svn.ra.do_update(self._ra, revnum, "", 
                             *args, **kwargs))

    def supports_custom_revprops(self):
        return has_attr(svn.ra, 'get_commit_editor3')

    @convert_svn_error
    def get_commit_editor(self, revprops, done_cb, lock_token, keep_locks):
        self._open_real_transport()
        self._mark_busy()
        if revprops.keys() == [svn.core.SVN_PROP_REVISION_LOG]:
            editor = svn.ra.get_commit_editor(self._ra, 
                        revprops[svn.core.SVN_PROP_REVISION_LOG],
                        done_cb, lock_token, keep_locks)
        else:
            editor = svn.ra.get_commit_editor3(self._ra, revprops, done_cb, 
                                              lock_token, keep_locks)
        return Editor(self, editor)

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

    def lock_read(self, relpath):
        """See Transport.lock_read()."""
        return self.PhonyLock()

    def _is_http_transport(self):
        return (self.svn_url.startswith("http://") or 
                self.svn_url.startswith("https://"))

    def clone_root(self):
        if self._is_http_transport():
            return SvnRaTransport(self.get_repos_root(), 
                                  bzr_to_svn_url(self.base))
        return SvnRaTransport(self.get_repos_root())

    def clone(self, offset=None):
        """See Transport.clone()."""
        if offset is None:
            return SvnRaTransport(self.base)

        return SvnRaTransport(urlutils.join(self.base, offset))

    def local_abspath(self, relpath):
        """See Transport.local_abspath()."""
        absurl = self.abspath(relpath)
        if self.base.startswith("file:///"):
            return urlutils.local_path_from_url(absurl)
        raise NotLocalUrl(absurl)

    def abspath(self, relpath):
        """See Transport.abspath()."""
        return urlutils.join(self.base, relpath)
