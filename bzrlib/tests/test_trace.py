# Copyright (C) 2005, 2006 Canonical Ltd
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

from cStringIO import StringIO
import errno
import os
import sys

from bzrlib import (
    errors,
    plugin,
    trace,
    )
from bzrlib.tests import TestCaseInTempDir, TestCase, TestSkipped
from bzrlib.trace import mutter, report_exception


def _format_exception():
    """Format an exception as it would normally be displayed to the user"""
    buf = StringIO()
    report = report_exception(sys.exc_info(), buf)
    return buf.getvalue(), report


class TestTrace(TestCase):

    def test_format_sys_exception_no_apport(self):
        try:
            raise NotImplementedError, "time travel"
        except NotImplementedError:
            pass
        old_use_apport = trace._use_apport
        trace._use_apport = False
        try:
            err, report = _format_exception()
        finally:
            trace._use_apport = old_use_apport
        self.assertEqual(None, report)
        self.assertEqualDiff(err.splitlines()[0],
                'bzr: ERROR: exceptions.NotImplementedError: time travel')
        self.assertContainsRe(err,
                r'File.*test_trace.py')

    def test_format_sys_exception_apport(self):
        try:
            import problem_report
        except ImportError:
            raise TestSkipped('Apport not installed')
        try:
            raise NotImplementedError, "time travel"
        except NotImplementedError:
            pass
        old_argv = sys.argv
        sys.argv = ['foo', 'bar', 'quux']
        try:
            err, (report, report_filename) = _format_exception()
        finally:
            sys.argv = old_argv
        self.assertIsInstance(report, problem_report.ProblemReport)
        # the error formatting is checked by the blackbox ui command.
        # here we need to check that the file on disk - the problem report
        # will contain the right information.
        # the report needs:
        #  - the command line.
        #  - package data
        #  - plugins list
        #  - backtrace.
        # check the report logical data.
        self.assertEqual('foo bar quux', report['CommandLine'])
        known_plugins = ' '.join(plugin.all_plugins())
        self.assertEqual(known_plugins, report['BzrPlugins'])
        self.assertContainsRe(report['Traceback'], r'Traceback')
        # Stock apport facilities we just invoke, no need to test their
        # content
        self.assertNotEqual(None, report['Package'])
        self.assertNotEqual(None, report['Uname'])
        # check the file 'looks' like a good file, because we dont
        # want apport changes to break the user interface.
        report_file = file(report_filename, 'r')
        try:
            report_text = report_file.read()
        finally:
            report_file.close()
        # so we check this by looking across two fields and they should
        # be just \n separated.
        self.assertTrue('ProblemType: Crash\n'
            'BzrPlugins: ' in report_text)

    def test_format_interrupt_exception(self):
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            # XXX: Some risk that a *real* keyboard interrupt won't be seen
            # We can probably detect that by checking for the specific line
            # that we raise from in the test being in the backtrace.
            pass
        msg, report = _format_exception()
        self.assertTrue(len(msg) > 0)
        self.assertEqualDiff(msg, 'bzr: interrupted\n')

    def test_format_os_error(self):
        try:
            file('nosuchfile22222')
        except (OSError, IOError):
            pass
        msg, report = _format_exception()
        self.assertContainsRe(msg, r'^bzr: ERROR: \[Errno .*\] No such file.*nosuchfile')

    def test_format_unicode_error(self):
        try:
            raise errors.BzrCommandError(u'argument foo\xb5 does not exist')
        except errors.BzrCommandError:
            pass
        msg, report = _format_exception()

    def test_format_exception(self):
        """Short formatting of bzr exceptions"""
        try:
            raise errors.NotBranchError('wibble')
        except errors.NotBranchError:
            pass
        msg, report = _format_exception()
        self.assertTrue(len(msg) > 0)
        self.assertEqualDiff(msg, 'bzr: ERROR: Not a branch: wibble\n')

    def test_trace_unicode(self):
        """Write Unicode to trace log"""
        self.log(u'the unicode character for benzene is \N{BENZENE RING}')
        self.assertContainsRe(self._get_log(keep_log_file=True),
                              "the unicode character for benzene is")
    
    def test_trace_argument_unicode(self):
        """Write a Unicode argument to the trace log"""
        mutter(u'the unicode character for benzene is %s', u'\N{BENZENE RING}')
        self.assertContainsRe(self._get_log(keep_log_file=True),
                              'the unicode character')

    def test_trace_argument_utf8(self):
        """Write a Unicode argument to the trace log"""
        mutter(u'the unicode character for benzene is %s',
               u'\N{BENZENE RING}'.encode('utf-8'))
        self.assertContainsRe(self._get_log(keep_log_file=True),
                              'the unicode character')

    def test_report_broken_pipe(self):
        try:
            raise IOError(errno.EPIPE, 'broken pipe foofofo')
        except IOError, e:
            msg, report = _format_exception()
            self.assertEquals(msg, "bzr: broken pipe\n")
        else:
            self.fail("expected error not raised")

    def test_mutter_never_fails(self):
        # Even if the decode/encode stage fails, mutter should not
        # raise an exception
        mutter(u'Writing a greek mu (\xb5) works in a unicode string')
        mutter('But fails in an ascii string \xb5')
        mutter('and in an ascii argument: %s', '\xb5')
        log = self._get_log(keep_log_file=True)
        self.assertContainsRe(log, 'Writing a greek mu')
        self.assertContainsRe(log, "But fails in an ascii string")
        self.assertContainsRe(log, u"ascii argument: \xb5")
