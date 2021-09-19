#    test_revspec.py -- Test the revision specs
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

import os

from ....revisionspec import InvalidRevisionSpec, RevisionSpec

from ....tests.test_revisionspec import TestRevisionSpec

from . import Version, Changelog
from ..revspec import (
    UnknownVersion,
    VersionNotSpecified,
    RevisionSpec_package,
    RevisionSpec_upstream,
    )


class TestRevisionSpec_package(TestRevisionSpec):

    def test_from_string_package(self):
        spec = RevisionSpec.from_string('package:0.1-1')
        self.assertIsInstance(spec, RevisionSpec_package)
        self.assertEqual(spec.spec, '0.1-1')

    def test_simple_package(self):
        self.tree.branch.tags.set_tag('0.1-1', b'r1')
        self.assertInHistoryIs(1, b'r1', 'package:0.1-1')

    def test_unkown_version(self):
        self.assertRaises(
            UnknownVersion, self.get_in_history, 'package:0.1-1')

    def test_missing_version(self):
        self.assertRaises(
            VersionNotSpecified, self.get_in_history, 'package:')


class TestRevisionSpec_upstream(TestRevisionSpec):

    package_name = 'test'
    package_version = Version('0.1-1')
    upstream_version = property(
        lambda self: self.package_version.upstream_version)

    def make_changelog(self, version=None):
        if version is None:
            version = self.package_version
        c = Changelog()
        c.new_block()
        c.version = Version(version)
        c.package = self.package_name
        c.distributions = 'unstable'
        c.urgency = 'low'
        c.author = 'James Westby <jw+debian@jameswestby.net>'
        c.date = 'Thu,  3 Aug 2006 19:16:22 +0100'
        c.add_change('')
        c.add_change('  *  test build')
        c.add_change('')
        return c

    def write_changelog(self, changelog, filename):
        f = open(filename, 'w')
        changelog.write_to_open_file(f)
        f.close()

    def add_changelog(self, tree, version):
        cl = self.make_changelog("1.2-1")
        tree.mkdir('debian')
        self.write_changelog(
            cl, os.path.join(tree.basedir, 'debian/changelog'))
        tree.add(['debian', 'debian/changelog'])

    def test_from_string_package(self):
        self.make_branch_and_tree('.')
        spec = RevisionSpec.from_string('upstream:')
        self.assertIsInstance(spec, RevisionSpec_upstream)
        self.assertEqual(spec.spec, '')

    def test_no_changelog(self):
        t = self.make_branch_and_tree('.')
        spec = RevisionSpec.from_string('upstream:')
        self.assertRaises(InvalidRevisionSpec, spec.as_revision_id, t.branch)

    def test_version_specified(self):
        t = self.make_branch_and_tree('.')
        upstream_revid = t.commit('The upstream revision')
        t.branch.tags.set_tag("upstream-1.2", upstream_revid)
        t.commit('Mention upstream.')
        self.add_changelog(t, "1.2-1")
        spec = RevisionSpec.from_string('upstream:1.2')
        self.assertEquals(upstream_revid, spec.as_revision_id(t.branch))
        spec = RevisionSpec.from_string('upstream:1.2-1')
        self.assertEquals(upstream_revid, spec.as_revision_id(t.branch))

    def test_version_from_changelog(self):
        t = self.make_branch_and_tree('.')
        upstream_revid = t.commit('The upstream revision')
        t.branch.tags.set_tag("upstream-1.2", upstream_revid)
        t.commit('Mention upstream.')
        self.add_changelog(t, "1.2-1")
        spec = RevisionSpec.from_string('upstream:')
        self.assertEquals(upstream_revid, spec.as_revision_id(t.branch))
