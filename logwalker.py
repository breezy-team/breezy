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
from bzrlib.errors import NoSuchRevision, BzrError, NotBranchError
from bzrlib.progress import ProgressBar, DummyProgress
from bzrlib.trace import mutter

from svn.core import SubversionException
import svn.ra

import os
import pickle
from cStringIO import StringIO

cache_dir = os.path.join(config_dir(), 'svn-cache')

class NotSvnBranchPath(BzrError):
    def __init__(self, branch_path):
        BzrError.__init__(self, 
                "%r is not a valid Svn branch path", 
                branch_path)
        self.branch_path = branch_path

class LogWalker(object):
    def __init__(self, scheme, ra=None, uuid=None, last_revnum=None, repos_url=None, pb=ProgressBar()):
        if ra is None:
            callbacks = svn.ra.callbacks2_t()
            ra = svn.ra.open2(repos_url.encode('utf8'), callbacks, None, None)
            root = svn.ra.get_repos_root(ra)
            if root != repos_url:
                svn.ra.reparent(ra, root.encode('utf8'))

        if not uuid:
            uuid = svn.ra.get_uuid(ra)

        if last_revnum is None:
            last_revnum = svn.ra.get_latest_revnum(ra)

        self.cache_file = os.path.join(cache_dir, uuid)
        self.ra = ra
        self.scheme = scheme

        # Try to load cache from file
        try:
            self.revisions = pickle.load(open(self.cache_file))
            self.saved_revnum = len(self.revisions)-1
        except:
            self.revisions = {}
            self.saved_revnum = 0

        if self.saved_revnum < last_revnum:
            self.fetch_revisions(self.saved_revnum, last_revnum, pb)
        else:
            self.last_revnum = self.saved_revnum

    def fetch_revisions(self, from_revnum, to_revnum, pb=ProgressBar()):
        def rcvr(orig_paths, rev, author, date, message, pool):
            pb.update('fetching svn revision info', rev, to_revnum)
            paths = {}
            if orig_paths is None:
                orig_paths = {}
            for p in orig_paths:
                copyfrom_path = orig_paths[p].copyfrom_path
                if copyfrom_path:
                    copyfrom_path = copyfrom_path.strip("/")
                paths[p.strip("/")] = (orig_paths[p].action,
                            copyfrom_path, orig_paths[p].copyfrom_rev)

            self.revisions[rev] = {
                    'paths': paths,
                    'author': author,
                    'date': date,
                    'message': message
                    }

        self.last_revnum = to_revnum
        svn.ra.get_log(self.ra, ["/"], self.saved_revnum, to_revnum, 0, True, True, rcvr)
        pb.clear()

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
        for (branch, paths, rev, _, _, _) in self.get_branch_log(branch_path, 
                                                                 revnum):
            yield (branch, paths, rev)

    def get_branch_log(self, branch_path, from_revnum, to_revnum=0, limit=0):
        """Return iterator over all the revisions between from_revnum and 
        to_revnum that touch branch_path."""
        assert from_revnum >= to_revnum

        if not branch_path is None and not self.scheme.is_branch(branch_path):
            raise NotSvnBranchPath(branch_path)

        if branch_path:
            branch_path = branch_path.strip("/")

        if max(from_revnum, to_revnum) > self.last_revnum:
            try:
                self.fetch_revisions(self.last_revnum, max(from_revnum, to_revnum))
            except SubversionException, (msg, num):
                if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                    raise NoSuchRevision(branch=self, 
                        revision="Between %d and %d" % (from_revnum, to_revnum))
                raise

        continue_revnum = None
        num = 0
        for i in range(abs(from_revnum-to_revnum)+1):
            if to_revnum < from_revnum:
                i = from_revnum - i
            else:
                i = from_revnum + i

            if i == 0:
                continue

            if not (continue_revnum is None or continue_revnum == i):
                continue

            continue_revnum = None

            rev = self.revisions[i]
            changed_paths = {}
            for p in rev['paths']:
                mutter('eval: %r, %r' % (branch_path, p))
                if (branch_path is None or 
                    p == branch_path or
                    branch_path == "" or
                    p.startswith(branch_path+"/")):

                    try:
                        (bp, rp) = self.scheme.unprefix(p)
                        if not changed_paths.has_key(bp):
                            changed_paths[bp] = {}
                        changed_paths[bp][p] = rev['paths'][p]
                    except NotBranchError:
                        pass

            assert branch_path is None or len(changed_paths) <= 1

            for bp in changed_paths:
                num = num + 1
                yield (bp, changed_paths[bp], i, rev['author'], rev['date'], 
                       rev['message'])

            if (not branch_path is None and 
                branch_path in rev['paths'] and 
                not rev['paths'][branch_path][1] is None):
                # In this revision, this branch was copied from 
                # somewhere else
                # FIXME: What if copyfrom_path is not a branch path?
                continue_revnum = rev['paths'][branch_path][2]
                branch_path = rev['paths'][branch_path][1]

            if limit and num == limit:
                return

    def get_offspring(self, path, orig_revnum, revnum):
        """Check which files in revnum directly descend from path in orig_revnum."""
        assert orig_revnum <= revnum

        ancestors = [path]
        dest = (path, orig_revnum)

        for i in range(revnum-orig_revnum):
            paths = self.revisions[i+1+orig_revnum]['paths']
            for p in paths:
                new_ancestors = list(ancestors)

                if paths[p][0] in ('R', 'A') and paths[p][1]:
                    if paths[p][1:3] == dest:
                        new_ancestors.append(p)

                    for s in ancestors:
                        if s.startswith(paths[p][1]+"/"):
                            new_ancestors.append(s.replace(paths[p][1], p, 1))

                ancestors = new_ancestors

                if paths[p][0] in ('R', 'D'):
                    for s in ancestors:
                        if s == p or s.startswith(p+"/"):
                            new_ancestors.remove(s)

                ancestors = new_ancestors

        return ancestors
