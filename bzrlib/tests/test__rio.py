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

"""Tests for _rio_*."""

from bzrlib import (
    rio,
    tests,
    )


def load_tests(standard_tests, module, loader):
    # parameterize all tests in this module
    suite = loader.suiteClass()
    import bzrlib._rio_py as py_module
    scenarios = [('python', {'module': py_module})]
    if CompiledRioFeature.available():
        import bzrlib._rio_pyx as c_module
        scenarios.append(('C', {'module': c_module}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(CompiledRioFeature)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    tests.multiply_tests(standard_tests, scenarios, suite)
    return suite


class _CompiledRioFeature(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._rio_pyx
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._rio_pyx'

CompiledRioFeature = _CompiledRioFeature()


class TestValidTag(tests.TestCase):

    module = None # Filled in by test parameterization

    def test_ok(self):
        self.assertTrue(self.module._valid_tag("foo"))

    def test_no_spaces(self):
        self.assertFalse(self.module._valid_tag("foo bla"))

    def test_no_colon(self):
        self.assertFalse(self.module._valid_tag("foo:bla"))
    
    def test_type_error(self):
        self.assertRaises(TypeError, self.module._valid_tag, 423)

    def test_empty(self):
        self.assertFalse(self.module._valid_tag(""))
