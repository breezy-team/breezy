# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

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
"""Custom revision specifier for Subversion."""

from bzrlib.revisionspec import SPEC_TYPES, RevisionSpec

class RevisionSpec_svn(RevisionSpec):
    """Selects a revision using a Subversion revision number."""
    
    prefix = 'svn:'

    def _match_on(self, branch, revs):
        pass

    def needs_branch(self):
        return True

    def get_branch(self):
        return None


SPEC_TYPES.append(RevisionSpec_svn)
