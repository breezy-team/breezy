# Copyright (C) 2017 by Jelmer Vernooij
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

import sys
from unittest import TestLoader, TestSuite

from breezy.tests import TestCaseWithTransport


class SmokeTests(TestCaseWithTransport):

    def test_check_chk(self):
        out, err = self.run_bzr('check-chk')
        self.assertEqual(out, '')
        self.assertEqual(err, '')

    def test_chk_used_by(self):
        self.make_branch_and_tree('.')
        out, err = self.run_bzr('chk-used-by chk')
        self.assertEqual(out, '')
        self.assertEqual(err, '')

    def test_fetch_all_records(self):
        self.make_branch_and_tree('source')
        self.make_branch_and_tree('dest')
        out, err = self.run_bzr('fetch-all-records source -d dest')
        self.assertEqual(out, 'Done.\n')
        self.assertEqual(err, '')

    def test_file_refs(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add('foo')
        revid = tree.commit('a commit')
        out, err = self.run_bzr(
            'file-refs ' + tree.path2id('foo').decode() + ' ' + revid.decode())
        self.assertEqual(out, revid.decode('utf-8') + '\n')
        self.assertEqual(err, '')

    def test_fix_missing_keys_for_stacking(self):
        self.make_branch_and_tree('stacked')
        self.run_bzr('branch --stacked stacked new')
        out, err = self.run_bzr('fix-missing-keys-for-stacking new')
        self.assertEqual(out, '')
        self.assertEqual(err, '')

    def test_mirror_revs_into(self):
        self.make_branch_and_tree('source')
        self.make_branch_and_tree('dest')
        out, err = self.run_bzr('mirror-revs-into source dest')
        self.assertEqual(out, '')
        self.assertEqual(err, '')

    def test_repo_has_key(self):
        self.make_branch_and_tree('repo')
        out, err = self.run_bzr('repo-has-key repo revisions revid', retcode=1)
        self.assertEqual(out, 'False\n')
        self.assertEqual(err, '')

    def test_repo_keys(self):
        self.make_branch_and_tree('a')
        out, err = self.run_bzr('repo-keys a texts')
        self.assertEqual(out, '')
        self.assertEqual(err, '')


def test_suite():
    result = TestSuite()

    loader = TestLoader()
    result.addTests(loader.loadTestsFromModule(sys.modules[__name__]))
    return result
