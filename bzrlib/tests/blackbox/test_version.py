# Copyright (C) 2007 Canonical Ltd
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

"""Black-box tests for bzr version."""

import bzrlib
from bzrlib.tests import TestCase
from bzrlib import trace


class TestVersion(TestCase):

    def test_version(self):
        out = self.run_bzr("version")[0]
        self.assertTrue(len(out) > 0)
        self.assertEquals(1, out.count(bzrlib.__version__))
        self.assertContainsRe(out, r"(?m)^  Python interpreter:")
        self.assertContainsRe(out, r"(?m)^  Python standard library:")
        self.assertContainsRe(out, r"(?m)^  bzrlib:")
        self.assertContainsRe(out, r"(?m)^  Bazaar configuration:")
        self.assertContainsRe(out, r'(?m)^  Bazaar log file:.*bzr\.log')


class TestVersionUnicodeOutput(TestCase):

    def _check(self, args):
        old_trace_file = trace._bzr_log_filename
        trace._bzr_log_filename = u'/\u1234/.bzr.log'
        try:
            out = self.run_bzr(args)[0]
        finally:
            trace._bzr_log_filename = old_trace_file
        self.assertTrue(len(out) > 0)
        self.assertEquals(1, out.count(bzrlib.__version__))
        self.assertContainsRe(out, r"(?m)^  Python interpreter:")
        self.assertContainsRe(out, r"(?m)^  Python standard library:")
        self.assertContainsRe(out, r"(?m)^  bzrlib:")
        self.assertContainsRe(out, r"(?m)^  Bazaar configuration:")
        self.assertContainsRe(out, r'(?m)^  Bazaar log file:.*bzr\.log')

    def test_command(self):
        self._check("version")

    def test_flag(self):
        self._check("--version")
