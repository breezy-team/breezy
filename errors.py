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
"""Subversion-specific errors and conversion of Subversion-specific errors."""

from bzrlib.errors import BzrError, ConnectionReset, LockError

import svn.core

class NotSvnBranchPath(BzrError):
    """Error raised when a path was specified that did not exist."""
    _fmt = """{%(branch_path)s}:%(revnum)s is not a valid Svn branch path"""

    def __init__(self, branch_path, revnum=None):
        BzrError.__init__(self)
        self.branch_path = branch_path
        self.revnum = revnum


def convert_error(err):
    (num, msg) = err.args

    if num == svn.core.SVN_ERR_RA_SVN_CONNECTION_CLOSED:
        return ConnectionReset(msg=msg)
    elif num == svn.core.SVN_ERR_WC_LOCKED:
        return LockError(message=msg)
    else:
        return err


def convert_svn_error(unbound):
    """Decorator that catches particular Subversion exceptions and 
    converts them to Bazaar exceptions.
    """
    def convert(*args, **kwargs):
        try:
            return unbound(*args, **kwargs)
        except svn.core.SubversionException, e:
            raise convert_error(e)

    convert.__doc__ = unbound.__doc__
    convert.__name__ = unbound.__name__
    return convert


class NoCheckoutSupport(BzrError):

    _fmt = 'Subversion version too old for working tree support.'


class LocalCommitsUnsupported(BzrError):

    _fmt = 'Local commits are not supported for lightweight Subversion checkouts.'
