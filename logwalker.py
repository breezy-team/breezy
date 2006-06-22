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

from bzrlib.config import config_dir
from bzrlib.progress import ProgressBar
from bzrlib.trace import mutter

import svn.ra

import os
import pickle
from cStringIO import StringIO

cache_dir = os.path.join(config_dir(), 'svn-cache')

class LogWalker(object):
    def __init__(self, ra, uuid, last_revnum):
        self.cache_file = os.path.join(cache_dir, uuid)
        self.ra = ra

        # Try to load cache from file
        try:
            self.revisions = pickle.load(open(self.cache_file))
            self.saved_revnum = len(self.revisions)-1
        except:
            self.revisions = {}
            self.saved_revnum = 0

        from_revnum = self.saved_revnum
        self.update_revisions(from_revnum, last_revnum)

    def update_revisions(self, from_revnum, to_revnum):
        def rcvr(orig_paths, rev, author, date, message, pool):
            self.pb.update('fetching svn revision info', rev, to_revnum)
            paths = {}
            if orig_paths is None:
                orig_paths = {}
            for p in orig_paths:
                paths[p] = (orig_paths[p].action,
                            orig_paths[p].copyfrom_path,
                            orig_paths[p].copyfrom_rev)

            self.revisions[rev] = {
                    'paths': paths,
                    'author': author,
                    'date': date,
                    'message': message
                    }

        self.last_revnum = to_revnum
        if self.saved_revnum == to_revnum:
            return
        mutter('log -r %r:%r /' % (self.saved_revnum, to_revnum))
        self.pb = ProgressBar()
        svn.ra.get_log(self.ra, ["/"], self.saved_revnum, to_revnum, 0, True, True, rcvr)
        self.pb.clear()

    def __del__(self):
        if self.saved_revnum != self.last_revnum:
            self.save()

    def save(self):
        try:
            os.mkdir(cache_dir)
        except OSError:
            pass
        pickle.dump(self.revisions, open(self.cache_file, 'w'))

    def follow_history(self, branch_path, revnum):
        l = list(self.get_branch_log(branch_path, revnum, 0, 0, False))
        for (paths, rev, _, _, _) in l:
            yield (paths, rev)

    def get_branch_log(self, branch_path, from_revnum, to_revnum, limit, 
                strict_node_history):
        self.update_revisions(self.last_revnum, to_revnum)
        if branch_path is None:
            branch_path = ""
        num = 0
        for i in range(0, abs(from_revnum-to_revnum)+1):
            if to_revnum < from_revnum:
                i = from_revnum - i
            else:
                i = from_revnum + i
            if i == 0:
                continue

            rev = self.revisions[i]
            changed_paths = {}
            for p in rev['paths']:
                if p.startswith(branch_path) or p[1:].startswith(branch_path):
                    changed_paths[p] = rev['paths'][p]

            if len(changed_paths) == 0:
                continue

            num = num + 1
            yield (changed_paths, i, rev['author'], rev['date'], rev['message'])

            if limit and num == limit:
                return


