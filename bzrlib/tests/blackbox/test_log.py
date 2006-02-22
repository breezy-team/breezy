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


"""Black-box tests for bzr log.
"""


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
