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

from svn.core import SubversionException
from transport import SvnRaTransport
import svn.core

from bsddb import dbshelve as shelve

shelves = {}

def _escape_commit_message(message):
    """Replace xml-incompatible control characters."""
    import re
    # FIXME: RBC 20060419 this should be done by the revision
    # serialiser not by commit. Then we can also add an unescaper
    # in the deserializer and start roundtripping revision messages
    # precisely. See repository_implementations/test_repository.py
    
    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    message, _ = re.subn(
        u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
        lambda match: match.group(0).encode('unicode_escape'),
        message)
    return message


class NotSvnBranchPath(BzrError):
    _fmt = """{%(branch_path)s} is not a valid Svn branch path"""

    def __init__(self, branch_path):
        BzrError.__init__(self)
        self.branch_path = branch_path


class LogWalker(object):
    """Easy way to access the history of a Subversion repository."""
    def __init__(self, scheme, transport=None, cache_dir=None, last_revnum=None, pb=None):
        """Create a new instance.

        :param scheme:  Branching scheme to use.
        :param transport:   SvnRaTransport to use to access the repository.
        :param cache_dir:   Optional cache directory to use. Doesn't cache if 
                            not set.
        :param last_revnum: Last known revnum in the repository. Will be 
                            determined if not specified.
        :param pb:          Progress bar to report progress to.
        """
        assert isinstance(transport, SvnRaTransport)

        if last_revnum is None:
            last_revnum = transport.get_latest_revnum()

        self.last_revnum = last_revnum

        self.transport = transport.clone()
        self.scheme = scheme

        if not cache_dir is None:
            cache_file = os.path.join(cache_dir, 'log-v2')
            if not shelves.has_key(cache_file):
                shelves[cache_file] = shelve.open(cache_file)
            self.revisions = shelves[cache_file]
        else:
            self.revisions = {}
        self.saved_revnum = max(len(self.revisions)-1, 0)

    def fetch_revisions(self, to_revnum, pb=None):
        """Fetch information about all revisions in the remote repository
        until to_revnum.

        :param to_revnum: End of range to fetch information for
        :param pb: Optional progress bar to use
        """
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
            self.saved_revnum = rev

        to_revnum = max(self.last_revnum, to_revnum)

        # Don't bother for only a few revisions
        if abs(self.saved_revnum-to_revnum) < 10:
            pb = DummyProgress()
        else:
            pb = ProgressBar()

        try:
            try:
                mutter('getting log %r:%r' % (self.saved_revnum, to_revnum))
                self.transport.get_log(["/"], self.saved_revnum, to_revnum, 
                               0, True, True, rcvr)
            finally:
                pb.clear()
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(branch=self, 
                    revision="Revision number %d" % to_revnum)
            raise

    def follow_history(self, branch_path, revnum):
        """Return iterator over all the revisions between revnum and 
        0 that touch branch_path.
        
        :param branch_path:   Branch path to start reporting (in revnum)
        :param revnum:        Start revision.
        """
        assert revnum >= 0

        if not branch_path is None and not self.scheme.is_branch(branch_path):
            raise NotSvnBranchPath(branch_path)

        if branch_path:
            branch_path = branch_path.strip("/")

        if revnum > self.saved_revnum:
            self.fetch_revisions(revnum)

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
        """Find all branches that were changed in the specified revision number.

        :param revnum: Revision to search for branches.
        """
        created_branches = {}

        if revnum > self.saved_revnum:
            self.fetch_revisions(revnum)

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
        if revnum > self.saved_revnum:
            self.fetch_revisions(revnum, pb)
        rev = self.revisions[str(revnum)]
        if rev['author'] is None:
            author = None
        else:
            author = rev['author']
        return (author, 
             _escape_commit_message(rev['message']), 
             rev['date'], rev['paths'])

    
    def find_latest_change(self, path, revnum):
        """Find latest revision that touched path.

        :param path: Path to check for changes
        :param revnum: First revision to check
        """
        while revnum > 0 and not self.touches_path(path, revnum):
            revnum = revnum - 1
        return revnum

    def touches_path(self, path, revnum):
        """Check whether path was changed in specified revision.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        if revnum > self.saved_revnum:
            self.fetch_revisions(revnum)
        return (path in self.revisions[str(revnum)]['paths'])

    def find_children(self, path, revnum):
        """Find all children of path in revnum."""
        # TODO: Find children by walking history, or use 
        # cache?
        mutter("svn ls -r %d '%r'" % (revnum, path))

        try:
            (dirents, _, _) = self.transport.get_dir(
                "/" + path.encode('utf8'), revnum)
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NOT_DIRECTORY:
                return
            raise

        for p in dirents:
            yield os.path.join(path, p)
            for c in self.find_children(os.path.join(path, p), revnum):
                yield c
