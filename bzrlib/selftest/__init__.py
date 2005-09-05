# Copyright (C) 2005 by Canonical Ltd

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


import logging
import unittest
import tempfile
import os
import sys
import subprocess

from testsweet import run_suite
import bzrlib.commands

import bzrlib.trace
import bzrlib.fetch


MODULES_TO_TEST = []
MODULES_TO_DOCTEST = []

from logging import debug, warning, error

class CommandFailed(Exception):
    pass

class TestCase(unittest.TestCase):
    """Base class for bzr unit tests.
    
    Tests that need access to disk resources should subclass 
    TestCaseInTempDir not TestCase.

    Error and debug log messages are redirected from their usual
    location into a temporary file, the contents of which can be
    retrieved by _get_log().
       
    There are also convenience functions to invoke bzr's command-line
    routine, and to build and check bzr trees."""

    BZRPATH = 'bzr'

    def setUp(self):
        # this replaces the default testsweet.TestCase; we don't want logging changed
        unittest.TestCase.setUp(self)
        bzrlib.trace.disable_default_logging()
        self._enable_file_logging()


    def _enable_file_logging(self):
        fileno, name = tempfile.mkstemp(suffix='.log', prefix='testbzr')

        self._log_file = os.fdopen(fileno, 'w+')

        hdlr = logging.StreamHandler(self._log_file)
        hdlr.setLevel(logging.DEBUG)
        hdlr.setFormatter(logging.Formatter('%(levelname)4.4s  %(message)s'))
        logging.getLogger('').addHandler(hdlr)
        logging.getLogger('').setLevel(logging.DEBUG)
        self._log_hdlr = hdlr
        debug('opened log file %s', name)
        
        self._log_file_name = name

        
    def tearDown(self):
        logging.getLogger('').removeHandler(self._log_hdlr)
        bzrlib.trace.enable_default_logging()
        logging.debug('%s teardown', self.id())
        self._log_file.close()
        unittest.TestCase.tearDown(self)


    def log(self, *args):
        logging.debug(*args)

    def _get_log(self):
        """Return as a string the log for this test"""
        return open(self._log_file_name).read()

    def run_bzr(self, *args, **kwargs):
        """Invoke bzr, as if it were run from the command line.

        This should be the main method for tests that want to exercise the
        overall behavior of the bzr application (rather than a unit test
        or a functional test of the library.)

        Much of the old code runs bzr by forking a new copy of Python, but
        that is slower, harder to debug, and generally not necessary.
        """
        retcode = kwargs.get('retcode', 0)
        result = self.apply_redirected(None, None, None,
                                       bzrlib.commands.run_bzr, args)
        self.assertEquals(result, retcode)
        
        
    def check_inventory_shape(self, inv, shape):
        """
        Compare an inventory to a list of expected names.

        Fail if they are not precisely equal.
        """
        extras = []
        shape = list(shape)             # copy
        for path, ie in inv.entries():
            name = path.replace('\\', '/')
            if ie.kind == 'dir':
                name = name + '/'
            if name in shape:
                shape.remove(name)
            else:
                extras.append(name)
        if shape:
            self.fail("expected paths not found in inventory: %r" % shape)
        if extras:
            self.fail("unexpected paths found in inventory: %r" % extras)

    def apply_redirected(self, stdin=None, stdout=None, stderr=None,
                         a_callable=None, *args, **kwargs):
        """Call callable with redirected std io pipes.

        Returns the return code."""
        from StringIO import StringIO
        if not callable(a_callable):
            raise ValueError("a_callable must be callable.")
        if stdin is None:
            stdin = StringIO("")
        if stdout is None:
            stdout = self._log_file
        if stderr is None:
            stderr = self._log_file
        real_stdin = sys.stdin
        real_stdout = sys.stdout
        real_stderr = sys.stderr
        try:
            sys.stdout = stdout
            sys.stderr = stderr
            sys.stdin = stdin
            return a_callable(*args, **kwargs)
        finally:
            sys.stdout = real_stdout
            sys.stderr = real_stderr
            sys.stdin = real_stdin


BzrTestBase = TestCase

     
class TestCaseInTempDir(TestCase):
    """Derived class that runs a test within a temporary directory.

    This is useful for tests that need to create a branch, etc.

    The directory is created in a slightly complex way: for each
    Python invocation, a new temporary top-level directory is created.
    All test cases create their own directory within that.  If the
    tests complete successfully, the directory is removed.

    InTempDir is an old alias for FunctionalTestCase.
    """

    TEST_ROOT = None
    _TEST_NAME = 'test'
    OVERRIDE_PYTHON = 'python'

    def check_file_contents(self, filename, expect):
        self.log("check contents of file %s" % filename)
        contents = file(filename, 'r').read()
        if contents != expect:
            self.log("expected: %r" % expect)
            self.log("actually: %r" % contents)
            self.fail("contents of %s not as expected")

    def _make_test_root(self):
        import os
        import shutil
        import tempfile
        
        if TestCaseInTempDir.TEST_ROOT is not None:
            return
        TestCaseInTempDir.TEST_ROOT = os.path.abspath(
                                 tempfile.mkdtemp(suffix='.tmp',
                                                  prefix=self._TEST_NAME + '-',
                                                  dir=os.curdir))
    
        # make a fake bzr directory there to prevent any tests propagating
        # up onto the source directory's real branch
        os.mkdir(os.path.join(TestCaseInTempDir.TEST_ROOT, '.bzr'))

    def setUp(self):
        super(TestCaseInTempDir, self).setUp()
        import os
        self._make_test_root()
        self._currentdir = os.getcwdu()
        self.test_dir = os.path.join(self.TEST_ROOT, self.id())
        os.mkdir(self.test_dir)
        os.chdir(self.test_dir)
        
    def tearDown(self):
        import os
        os.chdir(self._currentdir)
        super(TestCaseInTempDir, self).tearDown()

    def _formcmd(self, cmd):
        if isinstance(cmd, basestring):
            cmd = cmd.split()
        if cmd[0] == 'bzr':
            cmd[0] = self.BZRPATH
            if self.OVERRIDE_PYTHON:
                cmd.insert(0, self.OVERRIDE_PYTHON)
        self.log('$ %r' % cmd)
        return cmd

    def runcmd(self, cmd, retcode=0):
        """Run one command and check the return code.

        Returns a tuple of (stdout,stderr) strings.

        If a single string is based, it is split into words.
        For commands that are not simple space-separated words, please
        pass a list instead."""
        cmd = self._formcmd(cmd)
        self.log('$ ' + ' '.join(cmd))
        actual_retcode = subprocess.call(cmd, stdout=self._log_file,
                                         stderr=self._log_file)
        if retcode != actual_retcode:
            raise CommandFailed("test failed: %r returned %d, expected %d"
                                % (cmd, actual_retcode, retcode))

    def backtick(self, cmd, retcode=0):
        """Run a command and return its output"""
        cmd = self._formcmd(cmd)
        child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=self._log_file)
        outd, errd = child.communicate()
        self.log(outd)
        actual_retcode = child.wait()

        outd = outd.replace('\r', '')

        if retcode != actual_retcode:
            raise CommandFailed("test failed: %r returned %d, expected %d"
                                % (cmd, actual_retcode, retcode))

        return outd



    def build_tree(self, shape):
        """Build a test tree according to a pattern.

        shape is a sequence of file specifications.  If the final
        character is '/', a directory is created.

        This doesn't add anything to a branch.
        """
        # XXX: It's OK to just create them using forward slashes on windows?
        import os
        for name in shape:
            assert isinstance(name, basestring)
            if name[-1] == '/':
                os.mkdir(name[:-1])
            else:
                f = file(name, 'wt')
                print >>f, "contents of", name
                f.close()
                


class MetaTestLog(TestCase):
    def test_logging(self):
        """Test logs are captured when a test fails."""
        logging.info('an info message')
        warning('something looks dodgy...')
        logging.debug('hello, test is running')
        ##assert 0


def selftest(verbose=False, pattern=".*"):
    return run_suite(test_suite(), 'testbzr', verbose=verbose, pattern=pattern)


def test_suite():
    from bzrlib.selftest.TestUtil import TestLoader, TestSuite
    import bzrlib, bzrlib.store, bzrlib.inventory, bzrlib.branch
    import bzrlib.osutils, bzrlib.commands, bzrlib.merge3, bzrlib.plugin
    from doctest import DocTestSuite
    import os
    import shutil
    import time
    import sys

    global MODULES_TO_TEST, MODULES_TO_DOCTEST

    testmod_names = \
                  ['bzrlib.selftest.MetaTestLog',
                   'bzrlib.selftest.test_parent',
                   'bzrlib.selftest.testinv',
                   'bzrlib.selftest.testfetch',
                   'bzrlib.selftest.versioning',
                   'bzrlib.selftest.whitebox',
                   'bzrlib.selftest.testmerge',
                   'bzrlib.selftest.testmerge3',
                   'bzrlib.selftest.testhashcache',
                   'bzrlib.selftest.teststatus',
                   'bzrlib.selftest.testlog',
                   'bzrlib.selftest.blackbox',
                   'bzrlib.selftest.testrevisionnamespaces',
                   'bzrlib.selftest.testbranch',
                   'bzrlib.selftest.testrevision',
                   'bzrlib.selftest.test_merge_core',
                   'bzrlib.selftest.test_smart_add',
                   'bzrlib.selftest.testdiff',
                   'bzrlib.fetch',
                   'bzrlib.selftest.teststore',
                   ]

    for m in (bzrlib.store, bzrlib.inventory, bzrlib.branch,
              bzrlib.osutils, bzrlib.commands, bzrlib.merge3):
        if m not in MODULES_TO_DOCTEST:
            MODULES_TO_DOCTEST.append(m)

    TestCase.BZRPATH = os.path.join(os.path.realpath(os.path.dirname(bzrlib.__path__[0])), 'bzr')
    print '%-30s %s' % ('bzr binary', TestCase.BZRPATH)
    print
    suite = TestSuite()
    suite.addTest(TestLoader().loadTestsFromNames(testmod_names))
    for m in MODULES_TO_TEST:
         suite.addTest(TestLoader().loadTestsFromModule(m))
    for m in (MODULES_TO_DOCTEST):
        suite.addTest(DocTestSuite(m))
    for p in bzrlib.plugin.all_plugins:
        if hasattr(p, 'test_suite'):
            suite.addTest(p.test_suite())
    return suite

