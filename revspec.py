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
from bzrlib.revisionspec import RevisionSpec, RevisionInfo, SPEC_TYPES

from bzrlib.plugins.builddeb.errors import (
        AmbiguousPackageSpecification,
        UnknownDistribution,
        UnknownVersion,
        VersionNotSpecified,
        )
from bzrlib.plugins.builddeb.util import lookup_distribution


class RevisionSpec_package(RevisionSpec):
    """Selects a revision based on the version of the package."""

    help_txt = """Selects the revision corresponding to a version of a package.

    Given a package version number this revision specifier will allow you
    specify the revision corresponding to the upload of that version of
    the package.
    """
    prefix = 'package:'

    def _match_on(self, branch, revs):
        loc = self.spec.find(':')
        if loc == -1:
            version_spec = self.spec
            dist_spec = None
        else:
            version_spec = self.spec[:loc]
            dist_spec = self.spec[loc+1:]

        if version_spec == '':
            raise VersionNotSpecified
        else:
            if dist_spec:
                # We were told a distribution, so use that
                dist_name = lookup_distribution(dist_spec)
                if dist_name is None:
                    if dist_spec not in ("debian", "ubuntu"):
                        raise UnknownDistribution(dist_spec)
                    dist_name = dist_spec
                tags_to_lookup = ("%s-%s" % (dist_name, version_spec),)
            else:
                # We weren't given a distribution, so try both and
                # see if there is ambiguity.
                tags_to_lookup = ("debian-%s" % version_spec,
                                  "ubuntu-%s" % version_spec)

        revision_id = None
        for tag_name in tags_to_lookup:
            tag_revid = None
            try:
                tag_revid = branch.tags.lookup_tag(tag_name)
            except NoSuchTag:
                pass
            if tag_revid is not None:
                if revision_id is not None:
                    raise AmbiguousPackageSpecification(self.prefix+self.spec)
                revision_id = tag_revid

        if revision_id is None:
            raise UnknownVersion(version_spec)
        return RevisionInfo.from_revision_id(branch,
                revision_id, revs)

SPEC_TYPES.append(RevisionSpec_package)

