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

from __future__ import absolute_import

from ...errors import (
    InvalidRevisionSpec,
    NoSuchTag,
    )
from ...revisionspec import RevisionSpec, RevisionInfo

from .errors import (
    MissingChangelogError,
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
            return RevisionInfo.from_revision_id(
                branch, revision_id)
        except NoSuchTag:
            raise UnknownVersion(version_spec)


class RevisionSpec_upstream(RevisionSpec):
    """Selects the matching upstream revision."""

    help_txt = """Selects the revision matching the upstream specified
    or the current upstream.

    This will look at debian/changelog to find out the current version,
    and then look up the upstream.
    """
    wants_revision_history = False
    prefix = 'upstream:'

    def _match_on(self, branch, revs):
        from ...workingtree import WorkingTree
        from .util import find_changelog
        from .upstream.pristinetar import PristineTarSource
        from debian.changelog import Version
        tree = WorkingTree.open_containing('.')[0]
        try:
            (cl, top_level) = find_changelog(tree, False)
        except MissingChangelogError as e:
            raise InvalidRevisionSpec(self.user_spec, branch,
                "no debian/changelog file found: %s" % e)
        if self.spec == '':
            version_spec = cl.version.upstream_version
            if not cl.version.debian_version:
                raise InvalidRevisionSpec(self.user_spec, branch,
                    "This is a native package.")
        else:
            version = Version(self.spec)
            if version.upstream_version:
                version_spec = version.upstream_version
            else:
                version_spec = self.spec

        pristine_tar_source = PristineTarSource(tree, branch)
        try:
            revision_id = pristine_tar_source.version_as_revisions(cl.package,
                version_spec)[None]
            return RevisionInfo.from_revision_id(
                branch, revision_id)
        except NoSuchTag:
            raise UnknownVersion(version_spec)
