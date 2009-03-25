# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Push implementation that simply prints message saying push is not supported."""

from bzrlib.repository import (
    InterRepository,
    )

from bzrlib.plugins.git.errors import (
    NoPushSupport,
    )
from bzrlib.plugins.git.repository import (
    GitRepository,
    GitRepositoryFormat,
    )

class InterToGitRepository(InterRepository):
    """InterRepository that copies into a Git repository."""

    _matching_repo_format = GitRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
            fetch_spec=None):
        raise NoPushSupport()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (not isinstance(source, GitRepository) and 
                isinstance(target, GitRepository))
