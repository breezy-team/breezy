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
"""Branching scheme implementations."""

from bzrlib import ui
from bzrlib.errors import BzrError
from bzrlib.trace import mutter

from errors import InvalidSvnBranchPath

from base64 import urlsafe_b64decode, urlsafe_b64encode
import bz2

class BranchingScheme:
    """ Divides SVN repository data up into branches. Since there
    is no proper way to do this, there are several subclasses of this class
    each of which handles a particular convention that may be in use.
    """
    def __init__(self):
        pass

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

    @staticmethod
    def find_scheme(name):
        """Find a branching scheme by name.

        :param name: Name of branching scheme.
        :return: Branching scheme instance.
        """
        assert isinstance(name, str)
        if name.startswith("trunk"):
            if name == "trunk":
                return TrunkBranchingScheme()
            try:
                return TrunkBranchingScheme(level=int(name[len("trunk"):]))
            except ValueError:
                raise UnknownBranchingScheme(name)

        if name == "none":
            return NoBranchingScheme()

        if name.startswith("single-"):
            return SingleBranchingScheme(name[len("single-"):])

        if name.startswith("list-"):
            return ListBranchingScheme(name[len("list-"):])

        raise UnknownBranchingScheme(name)

    def is_branch_parent(self, path):
        """Check whether the specified path is the parent directory of branches.
        The path may not be a branch itself.
        
        :param path: path to check
        :returns: boolean
        """
        raise NotImplementedError

    def is_tag_parent(self, path):
        """Check whether the specified path is the parent directory of tags.
        The path may not be a tag itself.
        
        :param path: path to check
        :returns: boolean
        """
        raise NotImplementedError

    def is_tag(self, path):
        """Check whether the specified path is a tag 
        according to this branching scheme.

        :param path: path to check
        :return: boolean
        """
        raise NotImplementedError

    def to_lines(self):
        """Generate a list of lines for this branching scheme.

        :return: List of lines representing the data in this branching 
            scheme.
        """
        raise NotImplementedError(self.to_lines)


def parse_list_scheme_text(text):
    """Parse a text containing the branches for a ListBranchingScheme.

    :param text: Text.
    :return: List of branch paths.
    """
    branches = []
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        branches.append(line.strip("/"))
    return branches


class ListBranchingScheme(BranchingScheme):
    """Branching scheme that keeps a list of branch paths, including 
    wildcards."""
    def __init__(self, branch_list):
        """Create new ListBranchingScheme instance.

        :param branch_list: List of know branch locations.
        """
        assert isinstance(branch_list, list) or isinstance(branch_list, str)
        if isinstance(branch_list, str):
            branch_list = bz2.decompress(urlsafe_b64decode(branch_list.encode("ascii").replace(".", "="))).splitlines()
        self.branch_list = [p.strip("/") for p in branch_list]
        self.split_branch_list = [p.split("/") for p in self.branch_list]

    def __str__(self):
        return "list-%s" % urlsafe_b64encode(bz2.compress("".join(map(lambda x:x+"\n", self.branch_list)))).replace("=", ".")

    def is_tag(self, path):
        """See BranchingScheme.is_tag()."""
        return False

    @staticmethod
    def _pattern_cmp(parts, pattern):
        if len(parts) != len(pattern):
            return False
        for (p, q) in zip(pattern, parts):
            if p != q and p != "*":
                return False
        return True

    def is_branch(self, path):
        """See BranchingScheme.is_branch()."""
        parts = path.strip("/").split("/")
        for pattern in self.split_branch_list:
            if self._pattern_cmp(parts, pattern):
                return True
        return False

    def unprefix(self, path):
        """See BranchingScheme.unprefix()."""
        assert isinstance(path, str)
        parts = path.strip("/").split("/")
        for pattern in self.split_branch_list:
            if self._pattern_cmp(parts[:len(pattern)], pattern):
                return ("/".join(parts[:len(pattern)]), 
                        "/".join(parts[len(pattern):]))
        raise InvalidSvnBranchPath(path=path, scheme=self)

    def __eq__(self, other):
        return self.branch_list == other.branch_list

    def to_lines(self):
        return self.branch_list

    def is_tag_parent(self, path):
        # ListBranchingScheme doesn't have tags
        return False

    def is_branch_parent(self, path):
        parts = path.strip("/").split("/")
        for pattern in self.split_branch_list:
            if len(parts) == len(pattern):
                continue
            if self._pattern_cmp(parts, pattern[0:len(parts)]):
                return True
        return False


class NoBranchingScheme(ListBranchingScheme):
    """Describes a scheme where there is just one branch, the 
    root of the repository."""
    def __init__(self):
        ListBranchingScheme.__init__(self, [""])

    def is_branch(self, path):
        """See BranchingScheme.is_branch()."""
        return path.strip("/") == ""

    def is_tag(self, path):
        return False

    def unprefix(self, path):
        """See BranchingScheme.unprefix()."""
        assert isinstance(path, str)
        return ("", path.strip("/"))

    def __str__(self):
        return "none"

    def __repr__(self):
        return "%s()" % self.__class__.__name__

    def is_branch_parent(self, path):
        return False

    def is_tag_parent(self, path):
        return False


class TrunkBranchingScheme(ListBranchingScheme):
    """Standard Subversion repository layout. 
    
    Each project contains three directories `trunk`, `tags` and `branches`. 
    """
    def __init__(self, level=0):
        self.level = level
        ListBranchingScheme.__init__(self,
            ["*/" * level + "trunk",
             "*/" * level + "branches/*",
             "*/" * level + "tags/*"])

    def is_branch(self, path):
        """See BranchingScheme.is_branch()."""
        parts = path.strip("/").split("/")
        if len(parts) == self.level+1 and parts[self.level] == "trunk":
            return True

        if len(parts) == self.level+2 and parts[self.level] == "branches":
            return True

        return False

    def is_tag(self, path):
        """See BranchingScheme.is_tag()."""
        parts = path.strip("/").split("/")
        if len(parts) == self.level+2 and \
           (parts[self.level] == "tags"):
            return True

        return False

    def unprefix(self, path):
        """See BranchingScheme.unprefix()."""
        assert isinstance(path, str)
        parts = path.strip("/").split("/")
        if len(parts) == 0 or self.level >= len(parts):
            raise InvalidSvnBranchPath(path=path, scheme=self)

        if parts[self.level] == "trunk" or parts[self.level] == "hooks":
            return ("/".join(parts[0:self.level+1]).strip("/"), 
                    "/".join(parts[self.level+1:]).strip("/"))
        elif ((parts[self.level] == "tags" or parts[self.level] == "branches") and 
              len(parts) >= self.level+2):
            return ("/".join(parts[0:self.level+2]).strip("/"), 
                    "/".join(parts[self.level+2:]).strip("/"))
        else:
            raise InvalidSvnBranchPath(path=path, scheme=self)

    def __str__(self):
        return "trunk%d" % self.level

    def __repr__(self):
        return "%s(%d)" % (self.__class__.__name__, self.level)

    def is_branch_parent(self, path):
        parts = path.strip("/").split("/")
        if len(parts) <= self.level:
            return True
        return self.is_branch(path+"/trunk")

    def is_tag_parent(self, path):
        parts = path.strip("/").split("/")
        return self.is_tag(path+"/aname")



class UnknownBranchingScheme(BzrError):
    _fmt = "Branching scheme could not be found: %(name)s"

    def __init__(self, name):
        self.name = name


class SingleBranchingScheme(ListBranchingScheme):
    """Recognizes just one directory in the repository as branch.
    """
    def __init__(self, path):
        self.path = path.strip("/")
        if self.path == "":
            raise BzrError("NoBranchingScheme should be used")
        ListBranchingScheme.__init__(self, [self.path])

    def is_branch(self, path):
        """See BranchingScheme.is_branch()."""
        return self.path == path.strip("/")

    def is_tag(self, path):
        """See BranchingScheme.is_tag()."""
        return False

    def unprefix(self, path):
        """See BranchingScheme.unprefix()."""
        assert isinstance(path, str)
        path = path.strip("/")
        if not path.startswith(self.path):
            raise InvalidSvnBranchPath(path=path, scheme=self)

        return (path[0:len(self.path)].strip("/"), 
                path[len(self.path):].strip("/"))

    def __str__(self):
        return "single-%s" % self.path

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.path)

    def is_branch_parent(self, path):
        if not "/" in self.path:
            return False
        return self.is_branch(path+"/"+self.path.split("/")[-1])

    def is_tag_parent(self, path):
        return False


def _find_common_prefix(paths):
    prefix = ""
    # Find a common prefix
    parts = paths[0].split("/")
    for i in range(len(parts)+1):
        for j in paths:
            if j.split("/")[:i] != parts[:i]:
                return prefix
        prefix = "/".join(parts[:i])
    return prefix


def find_commit_paths(changed_paths):
    """Find the commit-paths used in a bunch of revisions.

    :param changed_paths: List of changed_paths (dictionary with path -> action)
    :return: List of potential commit paths.
    """
    for changes in changed_paths:
        yield _find_common_prefix(changes.keys())


def guess_scheme_from_branch_path(relpath):
    """Try to guess the branching scheme from a branch path.

    :param relpath: Relative URL to a branch.
    :return: New BranchingScheme instance.
    """
    parts = relpath.strip("/").split("/")
    for i in range(0, len(parts)):
        if parts[i] == "trunk" and i == len(parts)-1:
            return TrunkBranchingScheme(level=i)
        elif parts[i] in ("branches", "tags") and i == len(parts)-2:
            return TrunkBranchingScheme(level=i)

    if parts == [""]:
        return NoBranchingScheme()
    return SingleBranchingScheme(relpath)


def guess_scheme_from_path(relpath):
    """Try to guess the branching scheme from a path in the repository, 
    not necessarily a branch path.

    :param relpath: Relative path in repository
    :return: New BranchingScheme instance.
    """
    parts = relpath.strip("/").split("/")
    for i in range(0, len(parts)):
        if parts[i] == "trunk":
            return TrunkBranchingScheme(level=i)
        elif parts[i] in ("branches", "tags"):
            return TrunkBranchingScheme(level=i)

    return NoBranchingScheme()


def guess_scheme_from_history(changed_paths, last_revnum, 
                              relpath=None):
    """Try to determine the best fitting branching scheme.

    :param changed_paths: Iterator over (branch_path, changes, revnum)
        as returned from LogWalker.follow_path().
    :param last_revnum: Number of entries in changed_paths.
    :param relpath: Branch path that should be accepted by the branching 
                    scheme as a branch.
    :return: Branching scheme instance that matches best.
    """
    potentials = {}
    pb = ui.ui_factory.nested_progress_bar()
    scheme_cache = {}
    try:
        for (bp, revpaths, revnum) in changed_paths:
            assert isinstance(revpaths, dict)
            pb.update("analyzing repository layout", last_revnum-revnum, 
                      last_revnum)
            for path in find_commit_paths([revpaths]):
                scheme = guess_scheme_from_path(path)
                if not potentials.has_key(str(scheme)):
                    potentials[str(scheme)] = 0
                potentials[str(scheme)] += 1
                scheme_cache[str(scheme)] = scheme
    finally:
        pb.finished()
    
    entries = potentials.items()
    entries.sort(lambda (a, b), (c, d): d - b)

    mutter('potential branching schemes: %r' % entries)

    if relpath is None:
        if len(entries) == 0:
            return NoBranchingScheme()
        return scheme_cache[entries[0][0]]

    for (schemename, _) in entries:
        scheme = scheme_cache[schemename]
        if scheme.is_branch(relpath):
            return scheme

    return guess_scheme_from_branch_path(relpath)


def scheme_from_branch_list(branch_list):
    """Determine a branching scheme for a branch list.

    :param branch_list: List of branch paths, may contain wildcards.
    :return: New branching scheme.
    """
    if branch_list == ["."] or branch_list == []:
        return NoBranchingScheme()
    if branch_list == TrunkBranchingScheme(0).branch_list:
        return TrunkBranchingScheme(0)
    return ListBranchingScheme(branch_list) 


help_schemes = """Subversion Branching Schemes

Subversion is basically a versioned file system. It does not have 
any notion of branches and what is a branch in Subversion is therefor
up to the user. 

In order for Bazaar to access a Subversion repository it has to know 
what paths to consider branches. It does this by using so-called branching 
schemes. When you connect to a repository for the first time, Bazaar
will try to determine the branching scheme to use using some simple 
heuristics. It is always possible to change the branching scheme it should 
use later.

There are some conventions in use in Subversion for repository layouts. 
The most common one is probably the trunk/branches/tags 
layout, where the repository contains a "trunk" directory with the main 
development branch, other branches in a "branches" directory and tags as 
subdirectories of a "tags" directory. This branching scheme is named 
"trunk" in Bazaar.

Another option is simply having just one branch at the root of the repository. 
This scheme is called "none" by Bazaar.

The branching scheme bzr-svn should use for a repository can be set in the 
configuration file ~/.bazaar/subversion.conf.
"""
