# Copyright (C) 2005, 2006 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
#            Martin Pool
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
from StringIO import StringIO

from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.trace import mutter, report_exception
from bzrlib.errors import NotBranchError, BzrError, BzrNewError


def _format_exception():
    """Format an exception as it would normally be displayed to the user"""
    buf = StringIO()
    report_exception(sys.exc_info(), buf)
    return buf.getvalue()


class TestTrace(TestCase):

    def test_format_sys_exception(self):
        try:
            raise NotImplementedError, "time travel"
        except NotImplementedError:
            pass
        err = _format_exception()
        self.assertEqualDiff(err.splitlines()[0],
                'bzr: ERROR: exceptions.NotImplementedError: time travel')
        self.assertContainsRe(err,
                r'File.*test_trace.py')

    def test_format_interrupt_exception(self):
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt():
            # XXX: Some risk that a *real* keyboard interrupt won't be seen
            pass
        msg = _format_exception()
        self.assertTrue(len(msg) > 0)
        self.assertEqualDiff(msg, 'bzr: interrupted\n')

    def test_format_exception(self):
        """Short formatting of bzr exceptions"""
        try:
            raise NotBranchError, 'wibble'
        except NotBranchError:
            pass
        msg = _format_exception()
        self.assertTrue(len(msg) > 0)
        self.assertEqualDiff(msg, 'bzr: ERROR: Not a branch: wibble\n')

    def test_format_old_exception(self):
        # format a class that doesn't descend from BzrNewError; 
        # remove this test when everything is unified there
        self.assertFalse(issubclass(BzrError, BzrNewError))
        try:
            raise BzrError('some old error')
        except BzrError:
            pass
        msg = _format_exception()
        self.assertEqualDiff(msg, 'bzr: ERROR: some old error\n')

    def test_trace_unicode(self):
        """Write Unicode to trace log"""
        self.log(u'the unicode character for benzene is \N{BENZENE RING}')
        self.assertContainsRe('the unicode character',
                self._get_log())
