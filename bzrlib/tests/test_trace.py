# Copyright (C) 2005-2011, 2016 Canonical Ltd
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

# "weren't nothing promised to you.  do i look like i got a promise face?"

"""Tests for trace library"""

from cStringIO import StringIO
import errno
import logging
import os
import re
import sys
import tempfile

from bzrlib import (
    debug,
    errors,
    trace,
    )
from bzrlib.tests import features, TestCaseInTempDir, TestCase
from bzrlib.trace import (
    mutter, mutter_callsite, report_exception,
    set_verbosity_level, get_verbosity_level, is_quiet, is_verbose, be_quiet,
    pop_log_file,
    push_log_file,
    _rollover_trace_maybe,
    show_error,
    )


def _format_exception():
    """Format an exception as it would normally be displayed to the user"""
    buf = StringIO()
    report_exception(sys.exc_info(), buf)
    return buf.getvalue()


class TestTrace(TestCase):

    def test_format_sys_exception(self):
        # Test handling of an internal/unexpected error that probably
        # indicates a bug in bzr.  The details of the message may vary
        # depending on whether apport is available or not.  See test_crash for
        # more.
        try:
            raise NotImplementedError, "time travel"
        except NotImplementedError:
            pass
        err = _format_exception()
        self.assertEqualDiff(err.splitlines()[0],
                'bzr: ERROR: exceptions.NotImplementedError: time travel')
        self.assertContainsRe(err,
            'Bazaar has encountered an internal error.')

    def test_format_interrupt_exception(self):
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            # XXX: Some risk that a *real* keyboard interrupt won't be seen
            pass
        msg = _format_exception()
        self.assertTrue(len(msg) > 0)
        self.assertEqualDiff(msg, 'bzr: interrupted\n')

    def test_format_memory_error(self):
        try:
            raise MemoryError()
        except MemoryError:
            pass
        msg = _format_exception()
        self.assertEqual(msg,
            "bzr: out of memory\nUse -Dmem_dump to dump memory to a file.\n")

    def test_format_mem_dump(self):
        self.requireFeature(features.meliae)
        debug.debug_flags.add('mem_dump')
        try:
            raise MemoryError()
        except MemoryError:
            pass
        msg = _format_exception()
        self.assertStartsWith(msg,
            "bzr: out of memory\nMemory dumped to ")

    def test_format_os_error(self):
        try:
            os.rmdir('nosuchfile22222')
        except OSError, e:
            e_str = str(e)
        msg = _format_exception()
        # Linux seems to give "No such file" but Windows gives "The system
        # cannot find the file specified".
        self.assertEqual('bzr: ERROR: %s\n' % (e_str,), msg)

    def test_format_io_error(self):
        try:
            file('nosuchfile22222')
        except IOError:
            pass
        msg = _format_exception()
        # Even though Windows and Linux differ for 'os.rmdir', they both give
        # 'No such file' for open()
        # However it now gets translated so we can not test for a specific message
        self.assertContainsRe(msg,
            r'^bzr: ERROR: \[Errno .*\] .*nosuchfile')

    def test_format_pywintypes_error(self):
        self.requireFeature(features.pywintypes)
        import pywintypes, win32file
        try:
            win32file.RemoveDirectory('nosuchfile22222')
        except pywintypes.error:
            pass
        msg = _format_exception()
        # GZ 2010-05-03: Formatting for pywintypes.error is basic, a 3-tuple
        #                with errno, function name, and locale error message
        self.assertContainsRe(msg,
            r"^bzr: ERROR: \(2, 'RemoveDirectory[AW]?', .*\)")
            
    def test_format_sockets_error(self):
        try:
            import socket
            sock = socket.socket()
            sock.send("This should fail.")
        except socket.error:
            pass
        msg = _format_exception()
        
        self.assertNotContainsRe(msg,
            r"Traceback (most recent call last):")

    def test_format_unicode_error(self):
        try:
            raise errors.BzrCommandError(u'argument foo\xb5 does not exist')
        except errors.BzrCommandError:
            pass
        msg = _format_exception()

    def test_format_exception(self):
        """Short formatting of bzr exceptions"""
        try:
            raise errors.NotBranchError('wibble')
        except errors.NotBranchError:
            pass
        msg = _format_exception()
        self.assertTrue(len(msg) > 0)
        self.assertEqualDiff(msg, 'bzr: ERROR: Not a branch: \"wibble\".\n')

    def test_report_external_import_error(self):
        """Short friendly message for missing system modules."""
        try:
            import ImaginaryModule
        except ImportError, e:
            pass
        else:
            self.fail("somehow succeeded in importing %r" % ImaginaryModule)
        msg = _format_exception()
        self.assertEqual(msg,
            'bzr: ERROR: No module named ImaginaryModule\n'
            'You may need to install this Python library separately.\n')

    def test_report_import_syntax_error(self):
        try:
            raise ImportError("syntax error")
        except ImportError, e:
            pass
        msg = _format_exception()
        self.assertContainsRe(msg,
            r'Bazaar has encountered an internal error')

    def test_trace_unicode(self):
        """Write Unicode to trace log"""
        self.log(u'the unicode character for benzene is \N{BENZENE RING}')
        log = self.get_log()
        self.assertContainsRe(log, "the unicode character for benzene is")

    def test_trace_argument_unicode(self):
        """Write a Unicode argument to the trace log"""
        mutter(u'the unicode character for benzene is %s', u'\N{BENZENE RING}')
        log = self.get_log()
        self.assertContainsRe(log, 'the unicode character')

    def test_trace_argument_utf8(self):
        """Write a Unicode argument to the trace log"""
        mutter(u'the unicode character for benzene is %s',
               u'\N{BENZENE RING}'.encode('utf-8'))
        log = self.get_log()
        self.assertContainsRe(log, 'the unicode character')

    def test_report_broken_pipe(self):
        try:
            raise IOError(errno.EPIPE, 'broken pipe foofofo')
        except IOError as e:
            msg = _format_exception()
            self.assertEqual(msg, "bzr: broken pipe\n")
        else:
            self.fail("expected error not raised")

    def assertLogStartsWith(self, log, string):
        """Like assertStartsWith, but skips the log timestamp."""
        self.assertContainsRe(log,
            '^\\d+\\.\\d+  ' + re.escape(string))

    def test_mutter_callsite_1(self):
        """mutter_callsite can capture 1 level of stack frame."""
        mutter_callsite(1, "foo %s", "a string")
        log = self.get_log()
        # begin with the message
        self.assertLogStartsWith(log, 'foo a string\nCalled from:\n')
        # should show two frame: this frame and the one above
        self.assertContainsRe(log,
            'test_trace\\.py", line \\d+, in test_mutter_callsite_1\n')
        # this frame should be the final one
        self.assertEndsWith(log, ' "a string")\n')

    def test_mutter_callsite_2(self):
        """mutter_callsite can capture 2 levels of stack frame."""
        mutter_callsite(2, "foo %s", "a string")
        log = self.get_log()
        # begin with the message
        self.assertLogStartsWith(log, 'foo a string\nCalled from:\n')
        # should show two frame: this frame and the one above
        self.assertContainsRe(log,
            'test_trace.py", line \d+, in test_mutter_callsite_2\n')
        # this frame should be the final one
        self.assertEndsWith(log, ' "a string")\n')

    def test_mutter_never_fails(self):
        # Even if the decode/encode stage fails, mutter should not
        # raise an exception
        # This test checks that mutter doesn't fail; the current behaviour
        # is that it doesn't fail *and writes non-utf8*.
        mutter(u'Writing a greek mu (\xb5) works in a unicode string')
        mutter('But fails in an ascii string \xb5')
        mutter('and in an ascii argument: %s', '\xb5')
        log = self.get_log()
        self.assertContainsRe(log, 'Writing a greek mu')
        self.assertContainsRe(log, "But fails in an ascii string")
        # However, the log content object does unicode replacement on reading
        # to let it get unicode back where good data has been written. So we
        # have to do a replaceent here as well.
        self.assertContainsRe(log, "ascii argument: \xb5".decode('utf8',
            'replace'))

    def test_show_error(self):
        show_error('error1')
        show_error(u'error2 \xb5 blah')
        show_error('arg: %s', 'blah')
        show_error('arg2: %(key)s', {'key':'stuff'})
        try:
            raise Exception("oops")
        except:
            show_error('kwarg', exc_info=True)
        log = self.get_log()
        self.assertContainsRe(log, 'error1')
        self.assertContainsRe(log, u'error2 \xb5 blah')
        self.assertContainsRe(log, 'arg: blah')
        self.assertContainsRe(log, 'arg2: stuff')
        self.assertContainsRe(log, 'kwarg')
        self.assertContainsRe(log, 'Traceback \\(most recent call last\\):')
        self.assertContainsRe(log, 'File ".*test_trace.py", line .*, in test_show_error')
        self.assertContainsRe(log, 'raise Exception\\("oops"\\)')
        self.assertContainsRe(log, 'Exception: oops')

    def test_push_log_file(self):
        """Can push and pop log file, and this catches mutter messages.

        This is primarily for use in the test framework.
        """
        tmp1 = tempfile.NamedTemporaryFile()
        tmp2 = tempfile.NamedTemporaryFile()
        try:
            memento1 = push_log_file(tmp1)
            mutter("comment to file1")
            try:
                memento2 = push_log_file(tmp2)
                try:
                    mutter("comment to file2")
                finally:
                    pop_log_file(memento2)
                mutter("again to file1")
            finally:
                pop_log_file(memento1)
            # the files were opened in binary mode, so should have exactly
            # these bytes.  and removing the file as the log target should
            # have caused them to be flushed out.  need to match using regexps
            # as there's a timestamp at the front.
            tmp1.seek(0)
            self.assertContainsRe(tmp1.read(),
                r"\d+\.\d+  comment to file1\n\d+\.\d+  again to file1\n")
            tmp2.seek(0)
            self.assertContainsRe(tmp2.read(),
                r"\d+\.\d+  comment to file2\n")
        finally:
            tmp1.close()
            tmp2.close()

    def test__open_bzr_log_uses_stderr_for_failures(self):
        # If _open_bzr_log cannot open the file, then we should write the
        # warning to stderr. Since this is normally happening before logging is
        # set up.
        self.overrideAttr(sys, 'stderr', StringIO())
        # Set the log file to something that cannot exist
        self.overrideEnv('BZR_LOG', os.getcwd() + '/no-dir/bzr.log')
        self.overrideAttr(trace, '_bzr_log_filename')
        logf = trace._open_bzr_log()
        self.assertIs(None, logf)
        self.assertContainsRe(sys.stderr.getvalue(),
                              'failed to open trace file: .*/no-dir/bzr.log')


class TestVerbosityLevel(TestCase):

    def test_verbosity_level(self):
        set_verbosity_level(1)
        self.assertEqual(1, get_verbosity_level())
        self.assertTrue(is_verbose())
        self.assertFalse(is_quiet())
        set_verbosity_level(-1)
        self.assertEqual(-1, get_verbosity_level())
        self.assertFalse(is_verbose())
        self.assertTrue(is_quiet())
        set_verbosity_level(0)
        self.assertEqual(0, get_verbosity_level())
        self.assertFalse(is_verbose())
        self.assertFalse(is_quiet())

    def test_be_quiet(self):
        # Confirm the old API still works
        be_quiet(True)
        self.assertEqual(-1, get_verbosity_level())
        be_quiet(False)
        self.assertEqual(0, get_verbosity_level())


class TestLogging(TestCase):
    """Check logging functionality robustly records information"""

    def test_note(self):
        trace.note("Noted")
        self.assertEqual("    INFO  Noted\n", self.get_log())

    def test_warning(self):
        trace.warning("Warned")
        self.assertEqual(" WARNING  Warned\n", self.get_log())

    def test_log(self):
        logging.getLogger("bzr").error("Errored")
        self.assertEqual("   ERROR  Errored\n", self.get_log())

    def test_log_sub(self):
        logging.getLogger("bzr.test_log_sub").debug("Whispered")
        self.assertEqual("   DEBUG  Whispered\n", self.get_log())

    def test_log_unicode_msg(self):
        logging.getLogger("bzr").debug(u"\xa7")
        self.assertEqual(u"   DEBUG  \xa7\n", self.get_log())

    def test_log_unicode_arg(self):
        logging.getLogger("bzr").debug("%s", u"\xa7")
        self.assertEqual(u"   DEBUG  \xa7\n", self.get_log())

    def test_log_utf8_msg(self):
        logging.getLogger("bzr").debug("\xc2\xa7")
        self.assertEqual(u"   DEBUG  \xa7\n", self.get_log())

    def test_log_utf8_arg(self):
        logging.getLogger("bzr").debug("%s", "\xc2\xa7")
        self.assertEqual(u"   DEBUG  \xa7\n", self.get_log())

    def test_log_bytes_msg(self):
        logging.getLogger("bzr").debug("\xa7")
        log = self.get_log()
        self.assertContainsString(log, "UnicodeDecodeError: ")
        self.assertContainsString(log,
            "Logging record unformattable: '\\xa7' % ()\n")

    def test_log_bytes_arg(self):
        logging.getLogger("bzr").debug("%s", "\xa7")
        log = self.get_log()
        self.assertContainsString(log, "UnicodeDecodeError: ")
        self.assertContainsString(log,
            "Logging record unformattable: '%s' % ('\\xa7',)\n")

    def test_log_mixed_strings(self):
        logging.getLogger("bzr").debug(u"%s", "\xa7")
        log = self.get_log()
        self.assertContainsString(log, "UnicodeDecodeError: ")
        self.assertContainsString(log,
            "Logging record unformattable: u'%s' % ('\\xa7',)\n")

    def test_log_repr_broken(self):
        class BadRepr(object):
            def __repr__(self):
                raise ValueError("Broken object")
        logging.getLogger("bzr").debug("%s", BadRepr())
        log = self.get_log()
        self.assertContainsRe(log, "ValueError: Broken object\n")
        self.assertContainsRe(log, "Logging record unformattable: '%s' % .*\n")


class TestBzrLog(TestCaseInTempDir):

    def test_log_rollover(self):
        temp_log_name = 'test-log'
        trace_file = open(temp_log_name, 'at')
        trace_file.writelines(['test_log_rollover padding\n'] * 200000)
        trace_file.close()
        _rollover_trace_maybe(temp_log_name)
        # should have been rolled over
        self.assertFalse(os.access(temp_log_name, os.R_OK))


class TestTraceConfiguration(TestCaseInTempDir):

    def test_default_config(self):
        config = trace.DefaultConfig()
        self.overrideAttr(trace, "_bzr_log_filename", None)
        trace._bzr_log_filename = None
        expected_filename = trace._get_bzr_log_filename()
        self.assertEqual(None, trace._bzr_log_filename)
        config.__enter__()
        try:
            # Should have entered and setup a default filename.
            self.assertEqual(expected_filename, trace._bzr_log_filename)
        finally:
            config.__exit__(None, None, None)
            # Should have exited and cleaned up.
            self.assertEqual(None, trace._bzr_log_filename)
