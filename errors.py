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

from bzrlib.errors import (BzrError, ConnectionError, ConnectionReset, 
                           LockError, NotBranchError, PermissionDenied, 
                           DependencyNotPresent, NoRepositoryPresent,
                           TransportError, UnexpectedEndOfContainerError)

import urllib
import svn.core


class InvalidExternalsDescription(BzrError):
    _fmt = """Unable to parse externals description."""


# APR define, not in svn.core
SVN_ERR_UNKNOWN_HOSTNAME = 670002

class NotSvnBranchPath(NotBranchError):
    """Error raised when a path was specified that did not exist."""
    _fmt = """%(path)s is not a valid Subversion branch path. 
See 'bzr help svn-branching-schemes' for details."""

    def __init__(self, branch_path, scheme=None):
        NotBranchError.__init__(self, urllib.quote(branch_path))
        self.scheme = scheme


class InvalidSvnBranchPath(NotBranchError):
    """Error raised when a path was specified that is not a child of or itself
    a valid branch path in the current branching scheme."""
    _fmt = """%(path)s is not a valid Subversion branch path in the current 
branching scheme. See 'bzr help svn-branching-schemes' for details."""

    def __init__(self, path, scheme):
        assert isinstance(path, str)
        NotBranchError.__init__(self, urllib.quote(path))
        self.scheme = scheme


class NoSvnRepositoryPresent(NoRepositoryPresent):

    def __init__(self, url):
        BzrError.__init__(self)
        self.path = url


class ChangesRootLHSHistory(BzrError):
    _fmt = """changing lhs branch history not possible on repository root"""


class MissingPrefix(BzrError):
    _fmt = """Prefix missing for %(path)s; please create it before pushing. """

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path


class RevpropChangeFailed(BzrError):
    _fmt = """Unable to set revision property %(name)s."""

    def __init__(self, name):
        BzrError.__init__(self)
        self.name = name


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
    elif num == svn.core.SVN_ERR_RA_SVN_MALFORMED_DATA:
        return TransportError("Malformed data", msg)
    elif num == svn.core.SVN_ERR_RA_NOT_IMPLEMENTED:
        return NotImplementedError("Function not implemented in remote server")
    elif num == SVN_ERR_UNKNOWN_HOSTNAME:
        return ConnectionError(msg=msg)
    elif num > 0 and num < 1000:
        return OSError(num, msg)
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


class InvalidFileName(BzrError):
    _fmt = "Unable to convert Subversion path %(path)s because it contains characters invalid in Bazaar."

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path


class CorruptMappingData(BzrError):
    _fmt = """An invalid change was made to the bzr-specific properties in %(path)s."""

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path
