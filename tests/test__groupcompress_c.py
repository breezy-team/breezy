# Copyright (C) 2008 Canonical Limited.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
# 

"""Tests for the pyrex extension of groupcompress"""

from bzrlib import tests


class _CompiledGroupCompress(tests.Feature):

    def _probe(self):
        try:
            import bzrlib.plugins.groupcompress._groupcompress_c
        except ImportError:
            return False
        else:
            return True

    def feature_name(self):
        return 'bzrlib.plugins.groupcompress._groupcompress_c'

CompiledGroupCompress = _CompiledGroupCompress()


class TestCompiledEquivalenceTable(tests.TestCase):
    """Direct tests for the compiled Equivalence Table."""

    _tests_need_features = [CompiledGroupCompress]

    def setUp(self):
        super(TestCompiledEquivalenceTable, self).setUp()
        from bzrlib.plugins.groupcompress import _groupcompress_c
        self._gc_module = _groupcompress_c

    def test_minimum_hash_size(self):
        eq = self._gc_module.EquivalenceTable([])
        self.assertEqual(1024, eq._py_compute_minimum_hash_size(1000))
        self.assertEqual(1024, eq._py_compute_minimum_hash_size(1024))
