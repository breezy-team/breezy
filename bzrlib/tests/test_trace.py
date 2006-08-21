# Copyright (C) 2005, 2006 by Canonical Ltd
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

import errno
import os
import sys
from StringIO import StringIO

from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.trace import mutter, report_exception
from bzrlib.errors import NotBranchError


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
        except KeyboardInterrupt:
            # XXX: Some risk that a *real* keyboard interrupt won't be seen
            pass
        msg = _format_exception()
        self.assertTrue(len(msg) > 0)
        self.assertEqualDiff(msg, 'bzr: interrupted\n')

    def test_format_os_error(self):
        try:
            file('nosuchfile22222')
        except (OSError, IOError):
            pass
        msg = _format_exception()
        self.assertContainsRe(msg, r'^bzr: ERROR: \[Errno .*\] No such file.*nosuchfile')


    def test_format_exception(self):
        """Short formatting of bzr exceptions"""
        try:
            raise NotBranchError, 'wibble'
        except NotBranchError:
            pass
        msg = _format_exception()
        self.assertTrue(len(msg) > 0)
        self.assertEqualDiff(msg, 'bzr: ERROR: Not a branch: wibble\n')

    def test_trace_unicode(self):
        """Write Unicode to trace log"""
        mutter(u'the unicode character for benzene is \N{BENZENE RING}')
        self._log_file.flush()
        self.assertContainsRe(self._get_log(), 'the unicode character',)
    
    def test_trace_argument_unicode(self):
        """Write a Unicode argument to the trace log"""
        mutter(u'the unicode character for benzene is %s', u'\N{BENZENE RING}')
        self._log_file.flush()
        self.assertContainsRe(self._get_log(), 'the unicode character')

    def test_trace_argument_utf8(self):
        """Write a Unicode argument to the trace log"""
        mutter(u'the unicode character for benzene is %s',
               u'\N{BENZENE RING}'.encode('utf-8'))
        self._log_file.flush()
        self.assertContainsRe(self._get_log(), 'the unicode character')

    def test_report_broken_pipe(self):
        try:
            raise IOError(errno.EPIPE, 'broken pipe foofofo')
        except IOError, e:
            msg = _format_exception()
            self.assertEquals(msg, "bzr: broken pipe\n")
        else:
            self.fail("expected error not raised")

    def test_mutter_never_fails(self):
        # Even if the decode/encode stage fails, mutter should not
        # raise an exception
        mutter(u'Writing a greek mu (\xb5) works in a unicode string')
        mutter('But fails in an ascii string \xb5')
        # TODO: jam 20051227 mutter() doesn't flush the log file, and
        #       self._get_log() opens the file directly and reads it.
        #       So we need to manually flush the log file
        import bzrlib.trace
        bzrlib.trace._trace_file.flush()
        log = self._get_log()
        self.assertContainsRe(log, 'Writing a greek mu')
        self.assertContainsRe(log, 'UnicodeError')
        self.assertContainsRe(log, "'But fails in an ascii string")
