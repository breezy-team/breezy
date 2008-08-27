# Copyright (C) 2007 Canonical Ltd
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

"""Converters, etc for going between Bazaar and Git ids."""

from bzrlib.plugins.git import foreign

class BzrGitMapping(foreign.VcsMapping):
    """Class that maps between Git and Bazaar semantics."""
    experimental = False

    def convert_revision_id_git_to_bzr(self, git_rev_id):
        """Convert a git revision id handle to a Bazaar revision id."""
        return "%s:%s" % (self.revid_prefix, git_rev_id)

    def convert_revision_id_bzr_to_git(self, bzr_rev_id):
        """Convert a Bazaar revision id to a git revision id handle."""
        assert bzr_rev_id.startswith("%s:" % self.namespace)
        return bzr_rev_id[len(self.revid_prefix)+1:]


class BzrGitMappingExperimental(BzrGitMapping):
    namespace = 'git-experimental'


default_mapping = BzrGitMappingExperimental()
