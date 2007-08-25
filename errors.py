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

from bzrlib.errors import (BzrError, ConnectionReset, LockError, 
                           NotBranchError, PermissionDenied, 
                           DependencyNotPresent, NoRepositoryPresent,
                           UnexpectedEndOfContainerError)

import svn.core

class NotSvnBranchPath(NotBranchError):
    """Error raised when a path was specified that did not exist."""
    _fmt = """%(path)s is not a valid Subversion branch path. 
See 'bzr help svn-branching-schemes' for details."""

    def __init__(self, branch_path, scheme=None):
        NotBranchError.__init__(self, branch_path)
        self.scheme = scheme


class NoSvnRepositoryPresent(NoRepositoryPresent):

    def __init__(self, url):
        BzrError.__init__(self)
        self.path = url


def convert_error(err):
    """Convert a Subversion exception to the matching BzrError.

    :param err: SubversionException.
    :return: BzrError instance if it could be converted, err otherwise
    """
    (msg, num) = err.args

    if num == svn.core.SVN_ERR_RA_SVN_CONNECTION_CLOSED:
        return ConnectionReset(msg=msg)
    elif num == svn.core.SVN_ERR_WC_LOCKED:
        return LockError(message=msg)
    elif num == svn.core.SVN_ERR_RA_NOT_AUTHORIZED:
        return PermissionDenied('.', msg)
    elif num == svn.core.SVN_ERR_INCOMPLETE_DATA:
        return UnexpectedEndOfContainerError()
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


class InvalidPropertyValue(BzrError):
    _fmt = 'Invalid property value for Subversion property %(property)s: %(msg)s'

    def __init__(self, property, msg):
        BzrError.__init__(self)
        self.property = property
        self.msg = msg

class RebaseNotPresent(DependencyNotPresent):
    _fmt = "Unable to import bzr-rebase (required for svn-upgrade support): %(error)s"

    def __init__(self, error):
        DependencyNotPresent.__init__(self, 'bzr-rebase', error)
