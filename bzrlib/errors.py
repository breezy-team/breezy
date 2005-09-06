#! /usr/bin/env python
# -*- coding: UTF-8 -*-

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


__copyright__ = "Copyright (C) 2005 Canonical Ltd."
__author__ = "Martin Pool <mbp@canonical.com>"


######################################################################
# exceptions 
class BzrError(StandardError):
    pass

class BzrCheckError(BzrError):
    pass


class InvalidRevisionNumber(BzrError):
    def __init__(self, revno):
        self.args = [revno]
        
    def __str__(self):
        return 'invalid revision number: %r' % self.args[0]


class InvalidRevisionId(BzrError):
    pass


class BzrCommandError(BzrError):
    # Error from malformed user command
    pass


class NotBranchError(BzrError):
    """Specified path is not in a branch"""
    pass


class NotVersionedError(BzrError):
    """Specified object is not versioned."""


class BadFileKindError(BzrError):
    """Specified file is of a kind that cannot be added.

    (For example a symlink or device file.)"""
    pass


class ForbiddenFileError(BzrError):
    """Cannot operate on a file because it is a control file."""
    pass


class LockError(Exception):
    """All exceptions from the lock/unlock functions should be from
    this exception class.  They will be translated as necessary. The
    original exception is available as e.original_error
    """
    def __init__(self, e=None):
        self.original_error = e
        if e:
            Exception.__init__(self, e)
        else:
            Exception.__init__(self)


class PointlessCommit(Exception):
    """Commit failed because nothing was changed."""


class NoSuchRevision(BzrError):
    def __init__(self, branch, revision):
        self.branch = branch
        self.revision = revision
        msg = "Branch %s has no revision %s" % (branch, revision)
        BzrError.__init__(self, msg)


class UnrelatedBranches(BzrCommandError):
    def __init__(self):
        msg = "Branches have no common ancestor, and no base revision"\
            " specified."
        BzrCommandError.__init__(self, msg)


class NotAncestor(BzrError):
    def __init__(self, rev_id, not_ancestor_id):
        self.rev_id = rev_id
        self.not_ancestor_id = not_ancestor_id
        msg = "Revision %s is not an ancestor of %s" % (not_ancestor_id, 
                                                        rev_id)
        BzrError.__init__(self, msg)


class InstallFailed(BzrError):
    def __init__(self, revisions):
        self.revisions = revisions
        msg = "Could not install revisions:\n%s" % " ,".join(revisions)
        BzrError.__init__(self, msg)


class AmbiguousBase(BzrError):
    def __init__(self, bases):
        msg = "The correct base is unclear, becase %s are all equally close" %\
            ", ".join(bases)
        BzrError.__init__(self, msg)
        self.bases = bases

