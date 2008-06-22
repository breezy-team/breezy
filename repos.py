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

import svn.repos

LOAD_UUID_IGNORE = svn.repos.load_uuid_ignore
LOAD_UUID_FORCE = svn.repos.load_uuid_force
LOAD_UUID_DEFAULT = svn.repos.load_uuid_default

def create(path):
    r = svn.repos.create(path, '', '', None, None)
    return Repository(path, r)

class Fs(object):
    def __init__(self, fs):
        self.fs = fs

    def get_uuid(self):
        return svn.fs.get_uuid(self.fs)


class Repository(object):
    def __init__(self, local_path, _repos=None):
        if _repos is not None:
            self.repos = _repos
        else:
            self.repos = svn.repos.svn_repos_open(local_path)

    def fs(self):
        return Fs(svn.repos.fs(self.repos))

    def load_fs(self, dumpstream, feedback_stream, uuid_action=LOAD_UUID_DEFAULT,
                parent_dir="", use_pre_commit_hook=False, use_post_commit_hook=False, 
                cancel_func=None):
        return svn.repos.load_fs2(self.repos, dumpstream, feedback_stream, uuid_action,
                parent_dir, use_pre_commit_hook, use_post_commit_hook, cancel_func)


