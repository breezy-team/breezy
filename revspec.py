#    util.py -- Utility functions
#    Copyright (C) 2008 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from bzrlib.errors import NoSuchTag
from bzrlib.revisionspec import RevisionSpec, RevisionInfo

from bzrlib.plugins.builddeb.errors import (
        UnknownVersion,
        VersionNotSpecified,
        )


class RevisionSpec_package(RevisionSpec):
    """Selects a revision based on the version of the package."""

    help_txt = """Selects the revision corresponding to a version of a package.

    Given a package version number this revision specifier will allow you
    specify the revision corresponding to the upload of that version of
    the package.
    """
    wants_revision_history = False
    prefix = 'package:'

    def _match_on(self, branch, revs):
        version_spec = self.spec
        dist_spec = None

        if version_spec == '':
            raise VersionNotSpecified

        try:
            revision_id = branch.tags.lookup_tag(version_spec)
            return RevisionInfo.from_revision_id(branch,
                    revision_id, revs)
        except NoSuchTag:
            raise UnknownVersion(version_spec)
