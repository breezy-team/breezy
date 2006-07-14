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

from bzrlib.errors import NoSuchRevision, BzrError, NotBranchError
from bzrlib.progress import ProgressBar, DummyProgress
from bzrlib.trace import mutter

import os
import shelve

from svn.core import SubversionException
import svn.ra

class NotSvnBranchPath(BzrError):
    def __init__(self, branch_path):
        BzrError.__init__(self, 
                "%r is not a valid Svn branch path", 
                branch_path)
        self.branch_path = branch_path


class LogWalker(object):
    def __init__(self, scheme, ra=None, cache_dir=None, last_revnum=None, repos_url=None, pb=None):
        if ra is None:
            callbacks = svn.ra.callbacks2_t()
            ra = svn.ra.open2(repos_url.encode('utf8'), callbacks, None, None)
            root = svn.ra.get_repos_root(ra)
            if root != repos_url:
                svn.ra.reparent(ra, root.encode('utf8'))

        if last_revnum is None:
            last_revnum = svn.ra.get_latest_revnum(ra)

        self.ra = ra
        self.scheme = scheme

        # Try to load cache from file
        if cache_dir is not None:
            self.revisions = shelve.open(os.path.join(cache_dir, 'log'))
        else:
            self.revisions = {}
        self.saved_revnum = max(len(self.revisions)-1, 0)

        if self.saved_revnum < last_revnum:
            self.fetch_revisions(self.saved_revnum, last_revnum, pb)
        else:
            self.last_revnum = self.saved_revnum

    def fetch_revisions(self, from_revnum, to_revnum, pb=None):
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

            self.revisions[str(rev)] = {
                    'paths': paths,
                    'author': author,
                    'date': date,
                    'message': message
                    }

        # Don't bother for only a few revisions
        if abs(self.saved_revnum-to_revnum) < 10:
            pb = DummyProgress()
        else:
            pb = ProgressBar()

        try:
            try:
                mutter('getting log %r:%r' % (self.saved_revnum, to_revnum))
                svn.ra.get_log(self.ra, ["/"], self.saved_revnum, to_revnum, 
                               0, True, True, rcvr)
                self.last_revnum = to_revnum
            finally:
                pb.clear()
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(branch=self, 
                    revision="Revision number %d" % to_revnum)
            raise

    def follow_history(self, branch_path, revnum):
        """Return iterator over all the revisions between from_revnum and 
        to_revnum that touch branch_path."""
        assert revnum >= 0

        if not branch_path is None and not self.scheme.is_branch(branch_path):
            raise NotSvnBranchPath(branch_path)

        if branch_path:
            branch_path = branch_path.strip("/")

        if revnum > self.last_revnum:
            self.fetch_revisions(self.last_revnum, revnum)

        continue_revnum = None
        for i in range(revnum+1):
            i = revnum - i

            if i == 0:
                continue

            if not (continue_revnum is None or continue_revnum == i):
                continue

            continue_revnum = None

            rev = self.revisions[str(i)]
            changed_paths = {}
            for p in rev['paths']:
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
                yield (bp, changed_paths[bp], i)

            if (not branch_path is None and 
                branch_path in rev['paths'] and 
                not rev['paths'][branch_path][1] is None):
                # In this revision, this branch was copied from 
                # somewhere else
                # FIXME: What if copyfrom_path is not a branch path?
                continue_revnum = rev['paths'][branch_path][2]
                branch_path = rev['paths'][branch_path][1]

    def find_branches(self, revnum):
        created_branches = {}

        for i in range(revnum):
            if i == 0:
                continue
            rev = self.revisions[str(i)]
            for p in rev['paths']:
                if self.scheme.is_branch(p):
                    if rev['paths'][p][0] in ('R', 'D'):
                        del created_branches[p]
                        yield (p, i, False)

                    if rev['paths'][p][0] in ('A', 'R'): 
                        created_branches[p] = i

        for p in created_branches:
            yield (p, i, True)

    def get_revision_info(self, revnum, pb=None):
        """Obtain basic information for a specific revision.

        :param revnum: Revision number.
        :returns: Tuple with author, log message and date of the revision.
        """
        if revnum > self.last_revnum:
            self.fetch_revisions(self.saved_revnum, revnum, pb)
        rev = self.revisions[str(revnum)]
        return (rev['author'], rev['message'], rev['date'], rev['paths'])
