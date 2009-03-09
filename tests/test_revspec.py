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

from bzrlib.tests.test_revisionspec import TestRevisionSpec

from bzrlib.revisionspec import RevisionSpec

from bzrlib.plugins.builddeb.errors import (
        UnknownVersion,
        VersionNotSpecified,
        )
from bzrlib.plugins.builddeb.revspec import RevisionSpec_package


class TestRevisionSpec_package(TestRevisionSpec):

    def test_from_string_package(self):
        spec = RevisionSpec.from_string('package:0.1-1')
        self.assertIsInstance(spec, RevisionSpec_package)
        self.assertEqual(spec.spec, '0.1-1')

    def test_simple_package(self):
        self.tree.branch.tags.set_tag('0.1-1', 'r1')
        self.assertInHistoryIs(1, 'r1', 'package:0.1-1')

    def test_unkown_version(self):
        self.assertRaises(UnknownVersion,
                self.get_in_history, 'package:0.1-1')

    def test_missing_version(self):
        self.assertRaises(VersionNotSpecified,
                self.get_in_history, 'package:')

