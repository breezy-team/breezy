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

from bzrlib.plugins.svn.ra import create_svn_client

import svn.client

class Client:
    def __init__(self, url=None):
        if url is not None:
            self.client_ctx = create_svn_client(url)
        else:
            self.client_ctx = svn.client.create_context()
            self.client_ctx.config = svn.core.svn_config_get_config(None)
        self.client_ctx.log_msg_func2 = \
                svn.client.svn_swig_py_get_commit_log_func

    def update(self, basedir, revision, recurse=True):
        return svn.client.update(basedir, revision, recurse, self.client_ctx)

    def checkout(self, url, path, revision, recurse=True):
        return svn.client.checkout(url, path, revision, recurse, self.client_ctx)

    def commit(self, targets, recursive=True, keep_locks=False):
        return svn.client.commit2(targets, recursive, keep_locks, self.client_ctx)

    def propset(self, name, value, path, recurse=True, skip_checks=False):
        return svn.client.propset2(name, value, path, recurse, skip_checks, self.client_ctx)

    def propget(self, name, path, rev, recurse=True):
        return svn.client.propget(name, path, rev, recurse, self.client_ctx)

    def revprop_get(self, name, url, rev):
        return svn.client.revprop_get(name, url, rev, self.client_ctx)

    def revprop_set(self, name, value, url, rev, force=False):
        return svn.client.revprop_set(name, value, url, rev, force, self.client_ctx)

    def add(self, relpath, recursive, force=False, noignore=False):
        return svn.client.add3(relpath, recursive, force, noignore, self.client_ctx)

    def delete(self, relpaths, force=False):
        return svn.client.delete2(relpaths, force, self.client_ctx)

    def copy(self, oldpath, rev, newpath):
        return svn.client.copy2(oldpath, rev, newpath, self.client_ctx)

    def log(self, targets, start, end, discover_changed_paths, strict_node_history, rcvr):
        return svn.client.log(targets, start, end, discover_changed_paths, strict_node_history, 
                              rcvr, self.client_ctx)
