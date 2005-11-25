# Copyright (C) 2005 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

# "weren't nothing promised to you.  do i look like i got a promise face?"

"""Tests for trace library"""

import os
import sys

from bzrlib.selftest import TestCaseInTempDir, TestCase
from bzrlib.trace import format_exception_short, mutter
from bzrlib.errors import NotBranchError

class TestTrace(TestCase):
    def test_format_sys_exception(self):
        """Short formatting of exceptions"""
        try:
            raise NotImplementedError, "time travel"
        except NotImplementedError:
            pass
        error_lines = format_exception_short(sys.exc_info()).splitlines()
        self.assertEqualDiff(error_lines[0], 
                'exceptions.NotImplementedError: time travel')
        self.assertContainsRe(error_lines[1], 
                r'^  at .*testtrace\.py line \d+$')  
        self.assertContainsRe(error_lines[2], 
                r'^  in test_format_sys_exception$')

    def test_format_exception(self):
        """Short formatting of exceptions"""
        try:
            raise NotBranchError, 'wibble'
        except NotBranchError:
            pass
        msg = format_exception_short(sys.exc_info())
        self.assertEqualDiff(msg, 'Not a branch: wibble')

    def test_trace_unicode(self):
        """Write Unicode to trace log"""
        self.log(u'the unicode character for benzene is \N{BENZENE RING}')
        self.assertContainsRe('the unicode character',
                self._get_log())
