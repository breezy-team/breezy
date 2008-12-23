# Copyright (C) 2008 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests that an enabled view is reported and impacts expected commands."""

from bzrlib import bzrdir
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree


class TestViewOps(TestCaseWithTransport):

    def make_abc_tree_with_ab_view(self):
        # we need to use a specific format because the default format
        # doesn't support views yet
        format = bzrdir.format_registry.make_bzrdir('1.12-preview')
        wt = TestCaseWithTransport.make_branch_and_tree(self, '.',
            format=format)
        self.build_tree(['a', 'b', 'c'])
        wt.views.set_view('my', ['a', 'b'])
        return wt

    def test_view_on_status(self):
        wt = self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr('status')
        self.assertEquals('ignoring files outside view: a, b\n', err)
        self.assertEquals('unknown:\n  a\n  b\n', out)

    def test_view_on_add(self):
        wt = self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr('add')
        self.assertEquals('ignoring files outside view: a, b\n', err)
        self.assertEquals('added a\nadded b\n', out)

    def test_view_on_diff(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('diff', retcode=1)
        self.assertEquals('*** ignoring files outside view: a, b\n', err)

    def test_view_on_commit(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('commit -m "testing commit"')
        err_lines = err.splitlines()
        self.assertEquals('ignoring files outside view: a, b', err_lines[0])
        self.assertStartsWith(err_lines[1], 'Committing to:')
        self.assertEquals('added a', err_lines[2])
        self.assertEquals('added b', err_lines[3])
        self.assertEquals('Committed revision 1.', err_lines[4])
        self.assertEquals('', out)

    def test_view_on_remove(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('remove --keep a')
        self.assertEquals('removed a\n', err)
        self.assertEquals('', out)
        out, err = self.run_bzr('remove --keep c', retcode=3)
        self.assertEquals('bzr: ERROR: Specified file "c" is outside the '
                          'current view: a, b\n', err)
        self.assertEquals('', out)
