
from bzrlib.tests.test_revisionspec import TestRevisionSpec

from bzrlib.revisionspec import RevisionSpec

from bzrlib.plugins.builddeb.errors import (
        AmbiguousPackageSpecification,
        UnknownDistribution,
        UnknownVersion,
        VersionNotSpecified,
        )
from bzrlib.plugins.builddeb.revspec import RevisionSpec_package


class TestRevisionSpec_package(TestRevisionSpec):

    def test_from_string_package(self):
        spec = RevisionSpec.from_string('package:0.1-1')
        self.assertIsInstance(spec, RevisionSpec_package)
        self.assertEqual(spec.spec, '0.1-1')
        spec = RevisionSpec.from_string('package:0.1-1:debian')
        self.assertIsInstance(spec, RevisionSpec_package)
        self.assertEqual(spec.spec, '0.1-1:debian')

    def test_simple_package(self):
        self.tree.branch.tags.set_tag('debian-0.1-1', 'r1')
        self.assertInHistoryIs(1, 'r1', 'package:0.1-1')
        self.assertInHistoryIs(1, 'r1', 'package:0.1-1:debian')

    def test_ambiguous_package(self):
        self.tree.branch.tags.set_tag('debian-0.1-1', 'r1')
        self.tree.branch.tags.set_tag('ubuntu-0.1-1', 'r2')
        self.assertRaises(AmbiguousPackageSpecification,
                self.get_in_history, 'package:0.1-1')
        self.assertInHistoryIs(1, 'r1', 'package:0.1-1:debian')
        self.assertInHistoryIs(2, 'r2', 'package:0.1-1:ubuntu')

    def test_unkown_distribution(self):
        self.assertRaises(UnknownDistribution,
                self.get_in_history, 'package:0.1-1:nonsense')

    def test_unkown_version(self):
        self.assertRaises(UnknownVersion,
                self.get_in_history, 'package:0.1-1')

    def test_missing_version(self):
        self.assertRaises(VersionNotSpecified,
                self.get_in_history, 'package:')

