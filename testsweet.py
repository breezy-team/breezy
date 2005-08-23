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


"""Enhanced layer on unittest.

This does several things:

* nicer reporting as tests run

* test code can log messages into a buffer that is recorded to disk
  and displayed if the test fails

* tests can be run in a separate directory, which is useful for code that
  wants to create files

* utilities to run external commands and check their return code
  and/or output

Test cases should normally subclass testsweet.TestCase.  The test runner should
call runsuite().

This is meant to become independent of bzr, though that's not quite
true yet.
"""  

import unittest
from unittest import TestResult

# XXX: Don't need this anymore now we depend on python2.4
def _need_subprocess():
    sys.stderr.write("sorry, this test suite requires the subprocess module\n"
                     "this is shipped with python2.4 and available separately for 2.3\n")
    

class CommandFailed(Exception):
    pass



class TestSkipped(Exception):
    """Indicates that a test was intentionally skipped, rather than failing."""
    # XXX: Not used yet


class TestCase(unittest.TestCase):
    """Base class for bzr test cases.

    Just defines some useful helper functions; doesn't actually test
    anything.
    """
    
    # TODO: Special methods to invoke bzr, so that we can run it
    # through a specified Python intepreter

    OVERRIDE_PYTHON = None # to run with alternative python 'python'
    BZRPATH = 'bzr'

    _log_buf = ""


    def setUp(self):
        super(TestCase, self).setUp()
        self.log("%s setup" % self.id())


    def tearDown(self):
        super(TestCase, self).tearDown()
        self.log("%s teardown" % self.id())
        self.log('')


    def formcmd(self, cmd):
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
        try:
            import shutil
            from subprocess import call
        except ImportError, e:
            _need_subprocess()
            raise


        cmd = self.formcmd(cmd)

        self.log('$ ' + ' '.join(cmd))
        actual_retcode = call(cmd, stdout=self.TEST_LOG, stderr=self.TEST_LOG)

        if retcode != actual_retcode:
            raise CommandFailed("test failed: %r returned %d, expected %d"
                                % (cmd, actual_retcode, retcode))


    def backtick(self, cmd, retcode=0):
        """Run a command and return its output"""
        try:
            import shutil
            from subprocess import Popen, PIPE
        except ImportError, e:
            _need_subprocess()
            raise

        cmd = self.formcmd(cmd)
        child = Popen(cmd, stdout=PIPE, stderr=self.TEST_LOG)
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


    def log(self, msg):
        """Log a message to a progress file"""
        # XXX: The problem with this is that code that writes straight
        # to the log file won't be shown when we display the log
        # buffer; would be better to not have the in-memory buffer and
        # instead just a log file per test, which is read in and
        # displayed if the test fails.  That seems to imply one log
        # per test case, not globally.  OK?
        self._log_buf = self._log_buf + str(msg) + '\n'
        print >>self.TEST_LOG, msg


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


    def check_file_contents(self, filename, expect):
        self.log("check contents of file %s" % filename)
        contents = file(filename, 'r').read()
        if contents != expect:
            self.log("expected: %r" % expect)
            self.log("actually: %r" % contents)
            self.fail("contents of %s not as expected")
            


class InTempDir(TestCase):
    """Base class for tests run in a temporary branch."""
    def setUp(self):
        import os
        self.test_dir = os.path.join(self.TEST_ROOT, self.__class__.__name__)
        os.mkdir(self.test_dir)
        os.chdir(self.test_dir)
        
    def tearDown(self):
        import os
        os.chdir(self.TEST_ROOT)





class _MyResult(TestResult):
    """
    Custom TestResult.

    No special behaviour for now.
    """
    def __init__(self, out, style):
        self.out = out
        TestResult.__init__(self)
        assert style in ('none', 'progress', 'verbose')
        self.style = style


    def startTest(self, test):
        # TODO: Maybe show test.shortDescription somewhere?
        what = test.id()
        # python2.3 has the bad habit of just "runit" for doctests
        if what == 'runit':
            what = test.shortDescription()
        
        if self.style == 'verbose':
            print >>self.out, '%-60.60s' % what,
            self.out.flush()
        elif self.style == 'progress':
            self.out.write('~')
            self.out.flush()
        TestResult.startTest(self, test)


    def stopTest(self, test):
        # print
        TestResult.stopTest(self, test)


    def addError(self, test, err):
        if self.style == 'verbose':
            print >>self.out, 'ERROR'
        TestResult.addError(self, test, err)
        _show_test_failure('error', test, err, self.out)

    def addFailure(self, test, err):
        if self.style == 'verbose':
            print >>self.out, 'FAILURE'
        TestResult.addFailure(self, test, err)
        _show_test_failure('failure', test, err, self.out)

    def addSuccess(self, test):
        if self.style == 'verbose':
            print >>self.out, 'OK'
        TestResult.addSuccess(self, test)



def run_suite(suite, name='test', verbose=False):
    import os
    import shutil
    import time
    import sys
    
    _setup_test_log(name)
    _setup_test_dir(name)
    print

    # save stdout & stderr so there's no leakage from code-under-test
    real_stdout = sys.stdout
    real_stderr = sys.stderr
    sys.stdout = sys.stderr = TestCase.TEST_LOG
    try:
        if verbose:
            style = 'verbose'
        else:
            style = 'progress'
        result = _MyResult(real_stdout, style)
        suite.run(result)
    finally:
        sys.stdout = real_stdout
        sys.stderr = real_stderr

    _show_results(result)

    return result.wasSuccessful()



def _setup_test_log(name):
    import time
    import os
    
    log_filename = os.path.abspath(name + '.log')
    TestCase.TEST_LOG = open(log_filename, 'wt', buffering=1) # line buffered

    print >>TestCase.TEST_LOG, "tests run at " + time.ctime()
    print '%-30s %s' % ('test log', log_filename)


def _setup_test_dir(name):
    import os
    import shutil
    
    TestCase.ORIG_DIR = os.getcwdu()
    TestCase.TEST_ROOT = os.path.abspath(name + '.tmp')

    print '%-30s %s' % ('running tests in', TestCase.TEST_ROOT)

    if os.path.exists(TestCase.TEST_ROOT):
        shutil.rmtree(TestCase.TEST_ROOT)
    os.mkdir(TestCase.TEST_ROOT)
    os.chdir(TestCase.TEST_ROOT)

    # make a fake bzr directory there to prevent any tests propagating
    # up onto the source directory's real branch
    os.mkdir(os.path.join(TestCase.TEST_ROOT, '.bzr'))

    

def _show_results(result):
     print
     print '%4d tests run' % result.testsRun
     print '%4d errors' % len(result.errors)
     print '%4d failures' % len(result.failures)



def _show_test_failure(kind, case, exc_info, out):
    from traceback import print_exception

    print >>out
    print >>out, '-' * 60
    print >>out, case
    
    desc = case.shortDescription()
    if desc:
        print >>out, '   (%s)' % desc
         
    print_exception(exc_info[0], exc_info[1], exc_info[2], None, out)
        
    if isinstance(case, TestCase):
        print >>out
        print >>out, 'log from this test:'
        print >>out, case._log_buf
         
    print >>out, '-' * 60
    

