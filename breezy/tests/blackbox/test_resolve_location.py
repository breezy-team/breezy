# Copyright (C) 2019 Breezy Developers
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


from breezy.tests import TestCaseWithTransport


class TestCatRevision(TestCaseWithTransport):

    def test_already_url(self):
        wt = self.make_branch_and_tree('.')

        out, err = self.run_bzr('resolve-location %s' % wt.branch.user_url)
        self.assertEqual(out, '%s\n' % wt.branch.user_url.replace('file://', ''))

    def test_parent_missing(self):
        wt = self.make_branch_and_tree('.')

        out, err = self.run_bzr('resolve-location :parent', retcode=3)
        self.assertEqual(out, '')
        self.assertEqual(err, 'brz: ERROR: No parent location assigned.\n')

    def test_parent(self):
        wt = self.make_branch_and_tree('.')
        wt.branch.set_parent('http://example.com/foo')

        out, err = self.run_bzr('resolve-location :parent')
        self.assertEqual(out, 'http://example.com/foo\n')
        self.assertEqual(err, '')
