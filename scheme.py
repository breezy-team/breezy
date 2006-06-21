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

from bzrlib.errors import NotBranchError

class BranchingScheme:
    """ Divides SVN repository data up into branches. Since there
    is no proper way to do this, there are several subclasses of this class
    each of which handles a particular convention that may be in use.
    """
    def is_branch(self, path):
        """Check whether a location refers to a branch.
        
        :param path: Path to check.
        """
        raise NotImplementedError

    def unprefix(self, path):
        """Split up a Subversion path into a branch-path and inside-branch path.

        :param path: Path to split up.
        :return: Tuple with branch-path and inside-branch path.
        """
        raise NotImplementedError


class TrunkBranchingScheme:
    def is_branch(self, path):
        """See BranchingScheme.is_branch()."""
        parts = path.strip("/").split("/")
        if len(parts) == 1 and parts[0] == "trunk":
            return True

        if len(parts) == 2 and (parts[0] == "branches" or parts[0] == "tags"):
            return True

        return False

    def unprefix(self, path):
        """See BranchingScheme.unprefix()."""
        parts = path.strip("/").split("/")
        if parts[0] == "trunk" or parts[0] == "hooks":
            return (parts[0], "/".join(parts[1:]))
        elif parts[0] == "tags" or parts[0] == "branches":
            return ("%s/%s" % (parts[0], parts[1]), "/".join(parts[2:]).strip("/"))
        else:
            raise NotBranchError(path=path)


class NoBranchingScheme:
    def is_branch(self, path):
        """See BranchingScheme.is_branch()."""
        return path.strip("/") == ""

    def unprefix(self, path):
        """See BranchingScheme.unprefix()."""
        return ("", path.strip("/"))


class ListBranchingScheme:
    def __init__(self, branch_list):
        """Create new ListBranchingScheme instance.

        :param branch_list: List of know branch locations.
        """
        self.branch_list = []
        for p in branch_list:
            self.branch_list.append(p.strip("/"))

    def is_branch(self, path):
        """See BranchingScheme.is_branch()."""
        return path.strip("/") in self.branch_list

    def unprefix(self, path):
        """See BranchingScheme.unprefix()."""
        path = path.strip("/")
        for i in self.branch_list:
            if (path+"/").startswith(i+"/"):
                return (i, path[len(i):].strip("/"))

        raise NotBranchError(path=path)
