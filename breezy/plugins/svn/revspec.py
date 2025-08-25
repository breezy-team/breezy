# Copyright (C) 2020 Jelmer Vernooij <jelmer@samba.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License or
# (at your option) a later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Revision specification support for Subversion revision numbers."""

from ...revisionspec import InvalidRevisionSpec, RevisionSpec


class RevisionSpec_svn(RevisionSpec):
    """Selects a revision using a Subversion revision number."""

    help_txt = """Selects a revision using a Subversion revision number (revno).

    Subversion revision numbers are per-repository whereas Bazaar revision
    numbers are per-branch. This revision specifier allows specifying
    a Subversion revision number.
    """

    prefix = "svn:"

    def _match_on(self, branch, revs):
        raise InvalidRevisionSpec(self.user_spec, branch)

    def needs_branch(self):
        """Check if this revision specifier needs a branch.

        Returns:
            True, as SVN revision specifiers require a branch context.
        """
        return True

    def get_branch(self):
        """Get the branch associated with this revision specifier.

        Returns:
            None, as this specifier doesn't provide a specific branch.
        """
        return None
