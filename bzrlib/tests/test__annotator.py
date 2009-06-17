# Copyright (C) 2009 Canonical Ltd
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

"""Tests for Annotators."""

from bzrlib import (
    errors,
    _annotator_py,
    tests,
    )


def load_tests(standard_tests, module, loader):
    """Parameterize tests for all versions of groupcompress."""
    scenarios = [
        ('python', {'module': _annotator_py}),
    ]
    suite = loader.suiteClass()
    if CompiledAnnotator.available():
        from bzrlib import _annotator_pyx
        scenarios.append(('C', {'module': _annotator_pyx}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(CompiledAnnotator)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    result = tests.multiply_tests(standard_tests, scenarios, suite)
    return result


class _CompiledAnnotator(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._annotator_pyx
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._annotator_pyx'

CompiledAnnotator = _CompiledAnnotator()


class TestAnnotator(tests.TestCaseWithMemoryTransport):

    module = None # Set by load_tests

    def make_single_text(self):
        repo = self.make_repository('repo')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        vf = repo.texts
        repo.start_write_group()
        vf.add_lines(('f-id', 'a-id'), (), ['simple\n', 'content\n'])
        repo.commit_write_group()
        return vf

    def test_annotate_missing(self):
        vf = self.make_single_text()
        ann = self.module.Annotator(vf)
        self.assertRaises(errors.RevisionNotPresent,
                          ann.annotate, ('not', 'present'))

    def test_annotate_simple(self):
        vf = self.make_single_text()
        ann = self.module.Annotator(vf)
        f_key = ('f-id', 'a-id')
        self.assertEqual(([(f_key,)]*2, ['simple\n', 'content\n']),
                         ann.annotate(f_key))
