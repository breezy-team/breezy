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

from __future__ import absolute_import

from dulwich import errors as git_errors

from .. import errors as brz_errors


class BzrGitError(brz_errors.BzrError):
    """The base-level exception for bzr-git errors."""


class NoSuchRef(BzrGitError):
    """Raised when a ref can not be found."""

    _fmt = "The ref %(ref)s was not found in the repository at %(location)s."

    def __init__(self, ref, location, present_refs=None):
        self.ref = ref
        self.location = location
        self.present_refs = present_refs


def convert_dulwich_error(error):
    """Convert a Dulwich error to a Bazaar error."""

    if isinstance(error, git_errors.HangupException):
        raise brz_errors.ConnectionReset(error.msg, "")
    raise error


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


class UnknownCommitExtra(brz_errors.BzrError):
    _fmt = "Unknown extra fields in %(object)r: %(fields)r."

    def __init__(self, object, fields):
        brz_errors.BzrError.__init__(self)
        self.object = object
        self.fields = ",".join(fields)


class UnknownMercurialCommitExtra(brz_errors.BzrError):
    _fmt = "Unknown mercurial extra fields in %(object)r: %(fields)r."

    def __init__(self, object, fields):
        brz_errors.BzrError.__init__(self)
        self.object = object
        self.fields = b",".join(fields)
