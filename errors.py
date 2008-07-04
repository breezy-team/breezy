# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
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
                           TransportError, UnexpectedEndOfContainerError,
                           RedirectRequested)

import urllib
from bzrlib.plugins.svn import core


ERR_UNKNOWN_HOSTNAME = 670002
ERR_UNKNOWN_HOSTNAME = 670002
ERR_RA_SVN_CONNECTION_CLOSED = 210002
ERR_WC_LOCKED = 155004
ERR_RA_NOT_AUTHORIZED = 170001
ERR_INCOMPLETE_DATA = 200003
ERR_RA_SVN_MALFORMED_DATA = 210004
ERR_RA_NOT_IMPLEMENTED = 170003
ERR_FS_NO_SUCH_REVISION = 160006
ERR_FS_TXN_OUT_OF_DATE = 160028
ERR_REPOS_DISABLED_FEATURE = 165006
ERR_STREAM_MALFORMED_DATA = 140001
ERR_RA_ILLEGAL_URL = 170000
ERR_RA_LOCAL_REPOS_OPEN_FAILED = 180001
ERR_BAD_URL = 125002
ERR_RA_DAV_REQUEST_FAILED = 175002
ERR_RA_DAV_PATH_NOT_FOUND = 175007
ERR_FS_NOT_DIRECTORY = 160016
ERR_FS_NOT_FOUND = 160013
ERR_FS_ALREADY_EXISTS = 160020
ERR_RA_SVN_REPOS_NOT_FOUND = 210005
ERR_WC_NOT_DIRECTORY = 155007
ERR_ENTRY_EXISTS = 150002
ERR_WC_PATH_NOT_FOUND = 155010
ERR_CANCELLED = 200015
ERR_WC_UNSUPPORTED_FORMAT = 155021
ERR_UNKNOWN_CAPABILITY = 200026
ERR_AUTHN_NO_PROVIDER = 215001
ERR_RA_DAV_RELOCATED = 175011
ERR_FS_NOT_FILE = 160017


class NotSvnBranchPath(NotBranchError):
    """Error raised when a path was specified that did not exist."""
    _fmt = """%(path)s is not a valid Subversion branch path. 
See 'bzr help svn-branching-schemes' for details."""

    def __init__(self, branch_path, mapping=None):
        NotBranchError.__init__(self, urllib.quote(branch_path))
        self.mapping = mapping


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

    if num == ERR_RA_SVN_CONNECTION_CLOSED:
        return ConnectionReset(msg=msg)
    elif num == ERR_WC_LOCKED:
        return LockError(message=msg)
    elif num == ERR_RA_NOT_AUTHORIZED:
        return PermissionDenied('.', msg)
    elif num == ERR_INCOMPLETE_DATA:
        return UnexpectedEndOfContainerError()
    elif num == ERR_RA_SVN_MALFORMED_DATA:
        return TransportError("Malformed data", msg)
    elif num == ERR_RA_NOT_IMPLEMENTED:
        return NotImplementedError("Function not implemented in remote server")
    elif num == ERR_UNKNOWN_HOSTNAME:
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
        except core.SubversionException, e:
            raise convert_error(e)

    convert.__doc__ = unbound.__doc__
    convert.__name__ = unbound.__name__
    return convert


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


class InvalidSvnBranchPath(NotBranchError):
    """Error raised when a path was specified that is not a child of or itself
    a valid branch path in the current branching scheme."""
    _fmt = """%(path)s is not a valid Subversion branch path in the current 
repository layout. See 'bzr help svn-repository-layout' for details."""

    def __init__(self, path, layout):
        assert isinstance(path, str)
        NotBranchError.__init__(self, urllib.quote(path))
        self.layout = layout

