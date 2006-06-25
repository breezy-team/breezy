# Copyright (C) 2005-2006 Jelmer Vernooij <jelmer@samba.org>

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

from repository import SvnRepository

from bzrlib.decorators import needs_write_lock
from bzrlib.progress import ProgressBar
from bzrlib.repository import InterRepository

from svn.core import SubversionException
import svn.core

class InterSvnRepository(InterRepository):
    """Svn to any repository actions."""

    _matching_repo_format = None 
    """The format to test with - as yet there is no SvnRepoFormat."""

    @needs_write_lock
    def copy_content(self, revision_id=None, basis=None):
        """See InterRepository.copy_content."""
        pb = ProgressBar()

        # Loop over all the revnums until revision_id
        # (or youngest_revnum) and call self.target.add_revision() 
        # or self.target.add_inventory() each time

        if revision_id is None:
            path = ""
            until_revnum = svn.ra.get_latest_revnum(self.source.ra)
        else:
            (path, until_revnum) = self.source.parse_revision_id(revision_id)
        
        weave_store = self.target.weave_store

        transact = self.target.get_transaction()

        current = {}

        for (paths, revnum, _, _, _) in self.source._log.get_branch_log(path, 0, until_revnum, 0, False):
            pb.update('copying revision', revnum, until_revnum)
            assert path != None
            revid = self.source.generate_revision_id(revnum, path)
            assert revid != None
            if self.target.has_revision(revid):
                continue
            inv = self.source.get_inventory(revid)
            rev = self.source.get_revision(revid)
            self.target.add_revision(revid, rev, inv)

            #FIXME: use svn.ra.do_update
            for item in paths:
                (fileid, orig_revid) = self.source.path_to_file_id(revnum, item)
                branch_path = self.source.parse_revision_id(orig_revid)[0]
                if branch_path != path:
                    continue

                parents = []
                if current.has_key(fileid):
                    parents = [current[fileid]]

                current[fileid] = revid

                if paths[item][0] == 'A':
                    weave = weave_store.get_weave_or_empty(fileid, transact)
                elif paths[item][0] == 'M' or paths[item][0] == 'R':
                    weave = weave_store.get_weave(fileid, transact)
                elif paths[item][0] == 'D':
                    continue
                else:
                    raise BzrError("Unknown SVN action '%s'" % 
                        paths[item][0])
                
                lines = None
                try:
                    stream = self.source._get_file(item, revnum)
                    stream.seek(0)
                    lines = stream.readlines()
                except SubversionException, (_, num):
                    if num != svn.core.SVN_ERR_FS_NOT_FILE:
                        raise
                    lines = []

                if lines:
                    if not weave.has_version(revid):
                        weave.add_lines(revid, parents, lines)
            
        pb.clear()

    @needs_write_lock
    def fetch(self, revision_id=None, pb=None):
        """Fetch revisions. """
        self.copy_content(revision_id)

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with SvnRepository."""
        return isinstance(source, SvnRepository)


