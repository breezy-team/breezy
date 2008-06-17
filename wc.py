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

import svn.wc

SCHEDULE_NORMAL = svn.wc.schedule_normal
SCHEDULE_ADD = svn.wc.schedule_add
SCHEDULE_DELETE = svn.wc.schedule_delete
SCHEDULE_REPLACE = svn.wc.schedule_replace

class WorkingCopy:
    def __init__(self, associated, path, write_lock=False, depth=0, cancel_func=None):
        self.wc = svn.wc.adm_open3(associated, path, write_lock, depth, cancel_func)

    def prop_get(self, name, path):
        return svn.wc.prop_get(name, path, self.wc)

    def prop_set(self, name, value, path, skip_checks=False):
        return svn.wc.prop_set2(name, value, path, self.wc)

    def close(self):
        return svn.wc.adm_close(self.wc)

    def add(self, file_path, copyfrom_url=None, copyfrom_rev=-1, cancel_func=None, notify_func=None):
        return svn.wc.add2(file_path, self.wc, copyfrom_url, copyfrom_rev, cancel_func, notify_func)

    def delete(self, file_path, cancel_func=None, notify_func=None):
        return svn.wc.delete2(file_path, self.wc, cancel_func, notify_func)

    def copy(self, src, dst, cancel_func=None, notify_func=None):
        return svn.wc.copy(src, self.wc, dst, cancel_func, notify_func)

    def entries_read(self, show_hidden=False):
        return svn.wc.entries_read(self.wc, show_hidden)

    def entry(self, path, show_hidden=False):
        return svn.wc.entry(path, self.wc, show_hidden)

    def get_prop_diffs(self, relpath):
        props = svn.wc.get_prop_diffs(relpath, self.wc)
        if isinstance(props, list): # Subversion 1.5
            props = props[1]
        return props

    def process_committed(self, path, recurse, new_revnum, timestamp, committer, wcprop_changes=None, 
                          remove_lock=False):
        return svn.wc.process_committed2(path, self.wc, recurse, new_revnum, timestamp, committer,
                                         wcprop_changes, remove_lock)

get_default_ignores = svn.wc.get_default_ignores
get_adm_dir = svn.wc.get_adm_dir
is_adm_dir = svn.wc.is_adm_dir
get_pristine_copy_path = svn.wc.get_pristine_copy_path

def revision_status(path, trail_url=None, committed=True, cancel_func=None):
    return svn.wc.revision_status(path, trail_url, committed, cancel_func)
