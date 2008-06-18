# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import svn.core, svn.client, svn.delta, svn.ra

from bzrlib import debug, urlutils
from bzrlib.trace import mutter
from bzrlib.errors import InvalidURL, NoSuchFile, FileExists

from bzrlib.plugins.svn import properties
from bzrlib.plugins.svn.core import get_config, SubversionException

import bzrlib.plugins.svn.errors as svn_errors

def get_username_prompt_provider(fn, retries):
    def wrap_fn(realm, may_save, pool):
        username_cred = svn.core.svn_auth_cred_username_t()
        (username_cred.username, username_cred.may_save) = fn(realm, may_save)
        return username_cred
    return svn.core.svn_auth_get_username_prompt_provider(wrap_fn, retries)

def get_simple_prompt_provider(fn, retries):
    def wrap_fn(realm, username, may_save, pool):
        simple_cred = svn.core.svn_auth_cred_simple_t()
        (simple_cred.username, simple_cred.password, simple_cred.may_save) = \
                fn(realm, username, may_save)
        return simple_cred
    return svn.core.svn_auth_get_simple_prompt_provider(wrap_fn, retries)

def get_ssl_server_trust_prompt_provider(fn):
    def wrap_fn(realm, failures, cert_info, may_save, pool):
        ssl_server_trust = svn.core.svn_auth_cred_ssl_server_trust_t()
        (ssl_server_trust.accepted_failures, ssl_server_trust.may_save) = fn(realm, failures, cert_info, may_save)
        return ssl_server_trust
    return svn.core.svn_auth_get_ssl_server_trust_prompt_provider(wrap_fn)

def get_ssl_client_cert_pw_prompt_provider(fn, retries):
    def wrap_fn(realm, may_save, pool):
        ssl_cred_pw = svn.core.svn_auth_cred_ssl_client_cert_pw_t()
        (ssl_cred_pw.password, ssl_cred_pw.may_save) = fn(realm, may_save)
        return ssl_cred_pw
    return svn.core.svn_auth_get_ssl_client_cert_pw_prompt_provider(wrap_fn, retries)

get_simple_provider = svn.client.get_simple_provider
get_username_provider = svn.client.get_username_provider
get_ssl_client_cert_file_provider = svn.client.get_ssl_client_cert_file_provider
get_ssl_client_cert_pw_file_provider = svn.client.get_ssl_client_cert_pw_file_provider
get_ssl_server_trust_file_provider = svn.client.get_ssl_server_trust_file_provider
if hasattr(svn.client, 'get_windows_simple_provider'):
    get_windows_simple_provider = svn.client.get_windows_simple_provider
if hasattr(svn.client, 'get_keychain_simple_provider'):
    get_keychain_simple_provider = svn.client.get_keychain_simple_provider
if hasattr(svn.client, 'get_windows_ssl_server_trust_provider'):
    get_windows_ssl_server_trust_provider = svn.client.get_windows_ssl_server_trust_provider

txdelta_send_stream = svn.delta.svn_txdelta_send_stream

DIRENT_KIND = 0x0001

class FileEditor(object):
    def __init__(self, base_editor, baton):
        self.base_editor = base_editor
        self.baton = baton

    def apply_textdelta(self, base_checksum=None):
        assert self.base_editor.recent_baton[-1] == self.baton
        return svn.delta.editor_invoke_apply_textdelta(self.base_editor.editor, self.baton,
                base_checksum)

    def change_prop(self, name, value):
        assert self.base_editor.recent_baton[-1] == self.baton
        svn.delta.editor_invoke_change_file_prop(self.base_editor.editor, self.baton, name, 
                                                 value, None)

    def close(self, checksum=None):
        assert self.base_editor.recent_baton.pop() == self.baton
        svn.delta.editor_invoke_close_file(self.base_editor.editor, self.baton, checksum)


class DirEditor(object):
    def __init__(self, base_editor, baton):
        self.base_editor = base_editor
        self.baton = baton

    def close(self):
        assert self.base_editor.recent_baton.pop() == self.baton, \
                "only most recently opened baton can be closed"
        svn.delta.editor_invoke_close_directory(self.base_editor.editor, self.baton)

    def change_prop(self, name, value):
        assert self.base_editor.recent_baton[-1] == self.baton
        return svn.delta.editor_invoke_change_dir_prop(self.base_editor.editor, self.baton, 
                                                       name, value, None)

    def delete_entry(self, path, revnum):
        assert self.base_editor.recent_baton[-1] == self.baton
        return svn.delta.editor_invoke_delete_entry(self.base_editor.editor, path, revnum, self.baton, None)

    def add_file(self, path, copy_path=None, copy_revision=-1):
        assert self.base_editor.recent_baton[-1] == self.baton
        baton = svn.delta.editor_invoke_add_file(self.base_editor.editor, path, 
            self.baton, copy_path, copy_revision)
        self.base_editor.recent_baton.append(baton)
        return FileEditor(self.base_editor, baton)

    def open_file(self, path, base_revision=-1):
        assert self.base_editor.recent_baton[-1] == self.baton
        baton = svn.delta.editor_invoke_open_file(self.base_editor.editor, path, self.baton,
                                                 base_revision)
        self.base_editor.recent_baton.append(baton)
        return FileEditor(self.base_editor, baton)

    def add_directory(self, path, copy_path=None, copy_revision=-1):
        assert self.base_editor.recent_baton[-1] == self.baton
        baton = svn.delta.editor_invoke_add_directory(self.base_editor.editor, path, 
            self.baton, copy_path, copy_revision)
        self.base_editor.recent_baton.append(baton)
        return DirEditor(self.base_editor, baton)

    def open_directory(self, path, base_revision=-1):
        assert self.base_editor.recent_baton[-1] == self.baton
        baton = svn.delta.editor_invoke_open_directory(self.base_editor.editor, path, 
            self.baton, base_revision)
        self.base_editor.recent_baton.append(baton)
        return DirEditor(self.base_editor, baton)


class Editor(object):
    """Simple object wrapper around the Subversion delta editor interface."""
    def __init__(self, connection, (editor, editor_baton)):
        self.editor = editor
        self.editor_baton = editor_baton
        self.recent_baton = []
        self._connection = connection

    def set_target_revision(self, revnum):
        svn.delta.editor_invoke_set_target_revision(self.editor, self.editor_baton, revnum)        

    def open_root(self, base_revnum=-1):
        assert self.recent_baton == [], "root already opened"
        baton = svn.delta.editor_invoke_open_root(self.editor, 
                self.editor_baton, base_revnum)
        self.recent_baton.append(baton)
        return DirEditor(self, baton)

    def close(self):
        assert self.recent_baton == []
        svn.delta.editor_invoke_close_edit(self.editor, self.editor_baton)
        self._connection._unmark_busy()


class Auth:
    def __init__(self, providers=[]):
        self.providers = providers
        self.auth_baton = svn.core.svn_auth_open(self.providers)
        self.parameters = {}
        self.auth_baton._base = self.auth_baton # evil hack

    def set_parameter(self, name, value):
        self.parameters[name] = value
        svn.core.svn_auth_set_parameter(self.auth_baton, name, value)

    def get_parameter(self, name):
        return svn.core.svn_auth_get_parameter(self.auth_baton, name)


def needs_busy(unbound):
    """Decorator that marks a connection as busy before running a methd on it.
    """
    def convert(self, *args, **kwargs):
        self._mark_busy()
        try:
            return unbound(self, *args, **kwargs)
        finally:
            self._unmark_busy()

    convert.__doc__ = unbound.__doc__
    convert.__name__ = unbound.__name__
    return convert


def create_svn_client(url):
    from bzrlib.plugins.svn.auth import create_auth_baton
    client = svn.client.create_context()
    client.auth_baton = create_auth_baton(url)
    client.config = get_config(None)
    return client


class WrappedEditor:
    def __init__(self, actual):
        self.actual = actual

    def set_target_revision(self, revision):
        if getattr(self.actual, "set_target_revision", None) is not None:
            self.actual.set_target_revision(revision)

    def open_root(self, base_revision):
        if getattr(self.actual, "open_root", None) is not None:
            return self.actual.open_root(base_revision)
        return None

    def add_directory(self, path, baton, copyfrom_path, copyfrom_rev):
        if baton is not None and getattr(baton, "add_directory", None) is not None:
            return baton.add_directory(path, copyfrom_path, copyfrom_rev)
        return None

    def open_directory(self, path, baton, base_rev):
        if baton is not None and getattr(baton, "open_directory", None) is not None:
            return baton.open_directory(path, base_rev)
        return None

    def close_directory(self, baton):
        if baton is not None and getattr(baton, "close", None) is not None:
            return baton.close()

    def change_file_prop(self, baton, name, value):
        if baton is not None and getattr(baton, "change_prop", None) is not None:
            return baton.change_prop(name, value)

    def change_dir_prop(self, baton, name, value):
        if baton is not None and getattr(baton, "change_prop", None) is not None:
            return baton.change_prop(name, value)

    def apply_textdelta(self, baton, checksum):
        if baton is not None and getattr(baton, "apply_textdelta", None) is not None:
            return baton.apply_textdelta(checksum)

    def close_file(self, baton, checksum):
        if baton is not None and getattr(baton, "close", None) is not None:
            return baton.close(checksum)

    def open_file(self, path, baton, base_rev):
        if baton is not None and getattr(self.actual, "open_file", None) is not None:
            return baton.open_file(path, base_rev)
        return None

    def close_edit(self):
        if getattr(self.actual, "close_edit", None) is not None:
            self.actual.close_edit()


class RemoteAccess(object):
    """An single connection to a Subversion repository. This usually can 
    only do one operation at a time."""
    def __init__(self, url):
        self._busy = False
        self._root = None
        self._client = create_svn_client(url)
        self._unbusy_handler = None
        try:
            self.mutter('opening SVN RA connection to %r', url)
            self._ra = svn.client.open_ra_session(url.encode('utf8'), 
                    self._client)
        except SubversionException, (_, num):
            if num == svn_errors.ERR_RA_SVN_REPOS_NOT_FOUND:
                raise svn_errors.NoSvnRepositoryPresent(url=url)
            if num == svn_errors.ERR_BAD_URL:
                raise InvalidURL(url)
            raise
        self.url = url

    class Reporter(object):
        def __init__(self, connection, (reporter, report_baton)):
            self._reporter = reporter
            self._baton = report_baton
            self._connection = connection

        def set_path(self, path, revnum, start_empty, lock_token):
            svn.ra.reporter2_invoke_set_path(self._reporter, self._baton, 
                        path, revnum, start_empty, lock_token, None)

        def delete_path(self, path):
            svn.ra.reporter2_invoke_delete_path(self._reporter, self._baton,
                    path, None)

        def link_path(self, path, url, revision, start_empty, lock_token):
            svn.ra.reporter2_invoke_link_path(self._reporter, self._baton,
                    path, url, revision, start_empty, lock_token,
                    None)

        def finish(self):
            try:
                svn.ra.reporter2_invoke_finish_report(self._reporter, 
                        self._baton, None)
            finally:
                self._connection._unmark_busy()

        def abort(self):
            try:
                svn.ra.reporter2_invoke_abort_report(self._reporter, 
                        self._baton, None)
            finally:
                self._connection._unmark_busy()

    def is_busy(self):
        return self._busy

    def _mark_busy(self):
        assert not self._busy, "already busy"
        self._busy = True

    def set_unbusy_handler(self, handler):
        self._unbusy_handler = handler

    def _unmark_busy(self):
        assert self._busy, "not busy"
        self._busy = False
        if self._unbusy_handler is not None:
            self._unbusy_handler()
            self._unbusy_handler = None

    def mutter(self, text, *args):
        if 'transport' in debug.debug_flags:
            mutter(text, *args)

    @needs_busy
    def get_uuid(self):
        self.mutter('svn get-uuid')
        return svn.ra.get_uuid(self._ra)

    @needs_busy
    def get_repos_root(self):
        if self._root is None:
            self.mutter("svn get-repos-root")
            self._root = svn.ra.get_repos_root(self._ra)
        return self._root

    @needs_busy
    def get_latest_revnum(self):
        self.mutter("svn get-latest-revnum")
        return svn.ra.get_latest_revnum(self._ra)

    def _make_editor(self, editor):
        edit, edit_baton = svn.delta.make_editor(editor, None)
        self._edit = edit
        self._edit_baton = edit_baton
        return self._edit, self._edit_baton

    def do_switch(self, switch_rev, path, recurse, switch_url, editor):
        self.mutter('svn switch -r %d -> %r', switch_rev, switch_url)
        self._mark_busy()
        edit, edit_baton = self._make_editor(editor)
        return self.Reporter(self, svn.ra.do_switch(self._ra, switch_rev, path,
                             recurse, switch_url, edit, edit_baton, None))

    def change_rev_prop(self, revnum, name, value):
        self.mutter('svn revprop -r%d --set %s=%s', revnum, name, value)
        svn.ra.change_rev_prop(self._ra, revnum, name, value)

    @needs_busy
    def get_lock(self, path):
        return svn.ra.get_lock(self._ra, path)

    @needs_busy
    def unlock(self, locks, break_lock=False):
        def lock_cb(baton, path, do_lock, lock, ra_err, pool):
            pass
        return svn.ra.unlock(self._ra, locks, break_lock, lock_cb)
 
    @needs_busy
    def get_dir(self, path, revnum, kind=False):
        self.mutter("svn ls -r %d '%r'", revnum, path)
        assert len(path) == 0 or path[0] != "/"
        # ra_dav backends fail with strange errors if the path starts with a 
        # slash while other backends don't.
        if hasattr(svn.ra, 'get_dir2'):
            fields = 0
            if kind:
                fields += DIRENT_KIND
            return svn.ra.get_dir2(self._ra, path, revnum, fields)
        else:
            return svn.ra.get_dir(self._ra, path, revnum)

    @needs_busy
    def check_path(self, path, revnum):
        assert len(path) == 0 or path[0] != "/"
        self.mutter("svn check_path -r%d %s", revnum, path)
        return svn.ra.check_path(self._ra, path.encode('utf-8'), revnum)

    @needs_busy
    def mkdir(self, relpath, mode=None):
        assert len(relpath) == 0 or relpath[0] != "/"
        path = urlutils.join(self.url, relpath)
        try:
            svn.client.mkdir([path.encode("utf-8")], self._client)
        except SubversionException, (msg, num):
            if num == svn_errors.ERR_FS_NOT_FOUND:
                raise NoSuchFile(path)
            if num == svn_errors.ERR_FS_ALREADY_EXISTS:
                raise FileExists(path)
            raise

    def replay(self, revision, low_water_mark, send_deltas, editor):
        self.mutter('svn replay -r%r:%r', low_water_mark, revision)
        self._mark_busy()
        edit, edit_baton = self._make_editor(editor)
        svn.ra.replay(self._ra, revision, low_water_mark, send_deltas,
                      edit, edit_baton, None)

    def do_update(self, revnum, path, recurse, editor):
        self.mutter('svn update -r %r', revnum)
        self._mark_busy()
        edit, edit_baton = self._make_editor(editor)
        return self.Reporter(self, svn.ra.do_update(self._ra, revnum, path,
                             recurse, edit, edit_baton, None))

    def has_capability(self, cap):
        return svn.ra.has_capability(self._ra, cap)

    def revprop_list(self, revnum):
        self.mutter('svn revprop-list -r %r', revnum)
        return svn.ra.rev_proplist(self._ra, revnum, None)

    def get_commit_editor(self, revprops, done_cb=None, lock_token=None, keep_locks=False):
        self._mark_busy()
        try:
            if hasattr(svn.ra, 'get_commit_editor3'):
                editor = svn.ra.get_commit_editor3(self._ra, revprops, done_cb, 
                                                  lock_token, keep_locks)
            elif revprops.keys() != [properties.PROP_REVISION_LOG]:
                raise NotImplementedError()
            else:
                editor = svn.ra.get_commit_editor2(self._ra, 
                            revprops[properties.PROP_REVISION_LOG],
                            done_cb, lock_token, keep_locks)

            return Editor(self, editor)
        except:
            self._unmark_busy()
            raise

    class SvnLock(object):
        def __init__(self, connection, tokens):
            self._tokens = tokens
            self._connection = connection

        def unlock(self):
            self._connection.unlock(self.locks)

    @needs_busy
    def lock_write(self, path_revs, comment=None, steal_lock=False):
        tokens = {}
        def lock_cb(baton, path, do_lock, lock, ra_err, pool):
            tokens[path] = lock
        svn.ra.lock(self._ra, path_revs, comment, steal_lock, lock_cb)
        return SvnLock(self, tokens)

    @needs_busy
    def get_log(self, paths, from_revnum, to_revnum, limit, 
                discover_changed_paths, strict_node_history, revprops, rcvr):
        # No paths starting with slash, please
        assert paths is None or all([not p.startswith("/") for p in paths])
        if (paths is None and 
            (svn.core.SVN_VER_MINOR < 6 or (
             svn.core.SVN_VER_REVISION < 31470 and svn.core.SVN_VER_REVISION != 0))):
            paths = ["/"]
        self.mutter('svn log %r:%r %r (limit: %r)', from_revnum, to_revnum, paths, limit)
        if hasattr(svn.ra, 'get_log2'):
            return svn.ra.get_log2(self._ra, paths, 
                           from_revnum, to_revnum, limit, 
                           discover_changed_paths, strict_node_history, False, 
                           revprops, rcvr, None)

        class LogEntry(object):
            def __init__(self, changed_paths, rev, author, date, message):
                self.changed_paths = changed_paths
                self.revprops = {}
                if properties.PROP_REVISION_AUTHOR in revprops:
                    self.revprops[properties.PROP_REVISION_AUTHOR] = author
                if properties.PROP_REVISION_LOG in revprops:
                    self.revprops[properties.PROP_REVISION_LOG] = message
                if properties.PROP_REVISION_DATE in revprops:
                    self.revprops[properties.PROP_REVISION_DATE] = date
                # FIXME: Check other revprops
                # FIXME: Handle revprops is None
                self.revision = rev
                self.has_children = None

        def rcvr_convert(orig_paths, rev, author, date, message, pool):
            rcvr(LogEntry(orig_paths, rev, author, date, message), pool)

        return svn.ra.get_log(self._ra, paths, 
                              from_revnum, to_revnum, limit, discover_changed_paths, 
                              strict_node_history, rcvr_convert, None)

    @needs_busy
    def reparent(self, url):
        if self.url == url:
            return
        if hasattr(svn.ra, 'reparent'):
            self.mutter('svn reparent %r', url)
            svn.ra.reparent(self._ra, url)
            self.url = url
        else:
            raise NotImplementedError(self.reparent)



