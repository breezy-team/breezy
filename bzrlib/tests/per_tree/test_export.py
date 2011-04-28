# Copyright (C) 2011 Canocal Ltd
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

from __future__ import with_statement

import contextlib

from bzrlib.export import export
from bzrlib.tests.per_tree import TestCaseWithTree

@contextlib.contextmanager
def write_locked(tree):
    tree.lock_write()
    try:
        yield
    finally:
        tree.unlock()

class TestExport(TestCaseWithTree):

    def test_export_tar(self):
        work_a = self.make_branch_and_tree('wta')
        with write_locked(work_a):
            tree_a = self.workingtree_to_test_tree(work_a)
            export(tree_a, 'output', 'tar')
