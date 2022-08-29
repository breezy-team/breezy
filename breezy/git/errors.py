# Copyright (C) 2007 Canonical Ltd
# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""A grouping of Exceptions for bzr-git"""

from dulwich import errors as git_errors

from .. import errors as brz_errors


class BzrGitError(brz_errors.BzrError):
    """The base-level exception for bzr-git errors."""


class NoPushSupport(brz_errors.BzrError):
    _fmt = ("Push is not yet supported from %(source)r to %(target)r "
            "using %(mapping)r for %(revision_id)r. Try dpush instead.")

    def __init__(self, source, target, mapping, revision_id=None):
        self.source = source
        self.target = target
        self.mapping = mapping
        self.revision_id = revision_id


class GitSmartRemoteNotSupported(brz_errors.UnsupportedOperation):
    _fmt = "This operation is not supported by the Git smart server protocol."
