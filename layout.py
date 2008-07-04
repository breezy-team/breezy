# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib.errors import NotBranchError

class RepositoryLayout(object):
    """Describes a repository layout."""
    def get_tag_path(self, name, project=""):
        """Return the path at which the tag with specified name should be found.

        :param name: Name of the tag. 
        :param project: Optional name of the project the tag is for. Can include slashes.
        :return: Path of the tag."
        """
        raise NotImplementedError

    def get_branch_path(self, name, project=""):
        """Return the path at which the branch with specified name should be found.

        :param name: Name of the branch. 
        :param project: Optional name of the project the branch is for. Can include slashes.
        :return: Path of the branch.
        """
        raise NotImplementedError

    def parse(self, path):
        """Parse a path.

        :return: Tuple with type ('tag', 'branch'), project name, branch path and path 
            inside the branch
        """
        raise NotImplementedError

    def is_branch(self, path):
        """Check whether a specified path points at a branch."""
        try:
            (type, _, bp, rp) = self.parse(path)
        except NotBranchError:
            return False
        if type == "branch" and rp == "":
            return True
        return False

    def is_tag(self, path):
        """Check whether a specified path points at a tag."""
        try:
            (type, _, bp, rp) = self.parse(path)
        except NotBranchError:
            return False
        if type == "tag" and rp == "":
            return True
        return False

    def get_branches(self, revnum, project="", pb=None):
        """Retrieve a list of paths that refer to branches in a specific revision.

        :result: Iterator over tuples with (project, branch path)
        """
        raise NotImplementedError

    def get_tags(self, revnum, project="", pb=None):
        """Retrieve a list of paths that refer to tags in a specific revision.

        :result: Iterator over tuples with (project, branch path)
        """
        raise NotImplementedError
