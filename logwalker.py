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

import svn.ra

import os
import pickle
from cStringIO import StringIO

cache_dir = os.path.join(config_dir(), 'svn-cache')

class SvnLogWalker(object):
    def __init__(self, ra, uuid, to_revnum):
        cache_file = os.path.join(cache_dir, uuid)

        # Try to load cache from file
        try:
            self.revisions = pickle.load(open(cache_file))
            from_revnum = len(self.revisions)-1
        except:
            self.revisions = {}
            from_revnum = 0

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
        if from_revnum != to_revnum:
            mutter('log -r %r:%r /' % (from_revnum, to_revnum))
            self.pb = ProgressBar()

            svn.ra.get_log(ra, ["/"], from_revnum, to_revnum, 0, True, True, rcvr)
            self.pb.clear()
            try:
                os.mkdir(cache_dir)
            except OSError:
                pass
            pickle.dump(self.revisions, open(cache_file, 'w'))

    def follow_history(self, branch_path, revnum):
        for (paths, rev, author, date, message) in self.get_branch_log(branch_path, revnum, 0, 0, False):
            yield (paths, rev)

    def get_log(self, paths, from_revno, to_revno, limit, 
                strict_node_history):
        num = 0
        for i in range(0, abs(from_revno-to_revno)+1):
            if to_revno < from_revno:
                i = from_revno - i
            else:
                i = from_revno + i
            if i == 0:
                continue
            rev = self.revisions[i]
            changed_paths = {}
            for p in rev['paths']:
                for q in paths:
                    if p.startswith(q) or p[1:].startswith(q):
                        changed_paths[p] = rev['paths'][p]

            if len(changed_paths) > 0:
                num = num + 1
                yield (changed_paths, i, rev['author'], rev['date'], 
                     rev['message'])
                if limit and num == limit:
                    raise StopIteration
        
        raise StopIteration

    def get_branch_log(self, branch_path, from_revno, to_revno, limit, \
            strict_node_history):
        if branch_path is None:
            branch_path = ""
        self.get_log([branch_path], from_revno, to_revno, limit, 
                     strict_node_history)

