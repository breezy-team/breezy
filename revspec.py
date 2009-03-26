# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Custom revision specifier for Subversion."""

from bzrlib.errors import (
    BzrError,
    InvalidRevisionSpec,
    NoSuchRevision,
    )
from bzrlib.revisionspec import (
    RevisionInfo,
    RevisionSpec,
    )

from bzrlib.plugins.git import (
    lazy_check_versions,
    )

class RevisionSpec_git(RevisionSpec):
    """Selects a revision using a Subversion revision number."""

    help_txt = """Selects a revision using a Git revision sha1.
    """
    
    prefix = 'git:'

    def _match_on(self, branch, revs):
        lazy_check_versions()
        loc = self.spec.find(':')
        git_sha1 = self.spec[loc+1:].encode("utf-8")
        bzr_revid = branch.mapping.revision_id_foreign_to_bzr(git_sha1)
        if branch.repository.has_revision(bzr_revid):
            history = list(branch.repository.iter_reverse_revision_history(bzr_revid))
            history.reverse()
            return RevisionInfo.from_revision_id(branch, bzr_revid, history)
        raise InvalidRevisionSpec(self.user_spec, branch)

    def needs_branch(self):
        return True

    def get_branch(self):
        return None
