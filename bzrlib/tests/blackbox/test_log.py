# Copyright (C) 2005 by Canonical Ltd
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Black-box tests for bzr log."""

import os

from bzrlib.tests.blackbox import ExternalBase


class TestLog(ExternalBase):

    def _prepare(self):
        self.runbzr("init")
        self.build_tree(['hello.txt', 'goodbye.txt', 'meep.txt'])
        self.runbzr("add hello.txt")
        self.runbzr("commit -m message1 hello.txt")
        self.runbzr("add goodbye.txt")
        self.runbzr("commit -m message2 goodbye.txt")
        self.runbzr("add meep.txt")
        self.runbzr("commit -m message3 meep.txt")
        self.full_log = self.runbzr("log")[0]

    def test_log_null_end_revspec(self):
        self._prepare()
        self.assertTrue('revno: 1\n' in self.full_log)
        self.assertTrue('revno: 2\n' in self.full_log)
        self.assertTrue('revno: 3\n' in self.full_log)
        self.assertTrue('message:\n  message1\n' in self.full_log)
        self.assertTrue('message:\n  message2\n' in self.full_log)
        self.assertTrue('message:\n  message3\n' in self.full_log)

        log = self.runbzr("log -r 1..")[0]
        self.assertEquals(log, self.full_log)

    def test_log_null_begin_revspec(self):
        self._prepare()
        log = self.runbzr("log -r ..3")[0]
        self.assertEquals(self.full_log, log)

    def test_log_null_both_revspecs(self):
        self._prepare()
        log = self.runbzr("log -r ..")[0]
        self.assertEquals(self.full_log, log)

    def test_log_negative_begin_revspec_full_log(self):
        self._prepare()
        log = self.runbzr("log -r -3..")[0]
        self.assertEquals(self.full_log, log)

    def test_log_negative_both_revspec_full_log(self):
        self._prepare()
        log = self.runbzr("log -r -3..-1")[0]
        self.assertEquals(self.full_log, log)

    def test_log_negative_both_revspec_partial(self):
        self._prepare()
        log = self.runbzr("log -r -3..-2")[0]
        self.assertTrue('revno: 1\n' in log)
        self.assertTrue('revno: 2\n' in log)
        self.assertTrue('revno: 3\n' not in log)

    def test_log_negative_begin_revspec(self):
        self._prepare()
        log = self.runbzr("log -r -2..")[0]
        self.assertTrue('revno: 1\n' not in log)
        self.assertTrue('revno: 2\n' in log)
        self.assertTrue('revno: 3\n' in log)

    def test_log_postive_revspecs(self):
        self._prepare()
        log = self.runbzr("log -r 1..3")[0]
        self.assertEquals(self.full_log, log)


class TestLogMerges(ExternalBase):

    def test_merges_are_indented_by_level(self):
        self.build_tree(['parent/'])
        self.run_bzr('init', 'parent')
        self.run_bzr('commit', '-m', 'first post', '--unchanged', 'parent')
        self.run_bzr('branch', 'parent', 'child')
        self.run_bzr('commit', '-m', 'branch 1', '--unchanged', 'child')
        self.run_bzr('branch', 'child', 'smallerchild')
        self.run_bzr('commit', '-m', 'branch 2', '--unchanged', 'smallerchild')
        os.chdir('child')
        self.run_bzr('merge', '../smallerchild')
        self.run_bzr('commit', '-m', 'merge branch 2')
        os.chdir('../parent')
        self.run_bzr('merge', '../child')
        self.run_bzr('commit', '-m', 'merge branch 1')
        out,err = self.run_bzr('log')
        # the log will look something like:
#        self.assertEqual("""\
#------------------------------------------------------------
#revno: 2
#committer: Robert Collins <foo@example.com>
#branch nick: parent
#timestamp: Tue 2006-03-28 22:31:40 +1100
#message:
#  merge branch 1
#    ------------------------------------------------------------
#    merged: foo@example.com-20060328113140-91f43cfb46dc2863
#    committer: Robert Collins <foo@example.com>
#    branch nick: child
#    timestamp: Tue 2006-03-28 22:31:40 +1100
#    message:
#      merge branch 2
#        ------------------------------------------------------------
#        merged: foo@example.com-20060328113140-1ba24f850a0ef573
#        committer: Robert Collins <foo@example.com>
#        branch nick: smallerchild
#        timestamp: Tue 2006-03-28 22:31:40 +1100
#        message:
#          branch 2
#    ------------------------------------------------------------
#    merged: foo@example.com-20060328113140-5749a4757a8ac792
#    committer: Robert Collins <foo@example.com>
#    branch nick: child
#    timestamp: Tue 2006-03-28 22:31:40 +1100
#    message:
#      branch 1
#------------------------------------------------------------
#revno: 1
#committer: Robert Collins <foo@example.com>
#branch nick: parent
#timestamp: Tue 2006-03-28 22:31:39 +1100
#message:
#  first post
#""", out)
        # but we dont have a nice pattern matcher hooked up yet, so:
        # we check for the indenting of the commit message:
        self.assertTrue('  merge branch 1' in out)
        self.assertTrue('      merge branch 2' in out)
        self.assertTrue('          branch 2' in out)
        self.assertTrue('      branch 1' in out)
        self.assertTrue('  first post' in out)
        self.assertEqual('', err)
