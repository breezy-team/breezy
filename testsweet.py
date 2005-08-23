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
import sys

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

    def setUp(self):
        super(TestCase, self).setUp()
        # setup a temporary log for the test 
        import time
        import os
        import tempfile
        self.TEST_LOG = tempfile.NamedTemporaryFile(mode='wt', bufsize=0)
        # save stdout & stderr so there's no leakage from code-under-test
        self.real_stdout = sys.stdout
        self.real_stderr = sys.stderr
        sys.stdout = sys.stderr = self.TEST_LOG
        self.log("%s setup" % self.id())

    def tearDown(self):
        sys.stdout = self.real_stdout
        sys.stderr = self.real_stderr
        self.log("%s teardown" % self.id())
        self.log('')
        super(TestCase, self).tearDown()

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
     
    def _get_log(self):
        """Get the log the test case used. This can only be called once,
        after which an exception will be raised.
        """
        self.TEST_LOG.flush()
        log = open(self.TEST_LOG.name, 'rt').read()
        self.TEST_LOG.close()
        return log


class InTempDir(TestCase):
    """Base class for tests that use disk resources - i.e to run in a temporary
    branch.
    """

    TEST_ROOT = None
    _TEST_NAME = 'test'

    def _make_test_root(self):
        import os
        import shutil
        import tempfile
        
        if InTempDir.TEST_ROOT is not None:
            return
        InTempDir.TEST_ROOT = os.path.abspath(
                                 tempfile.mkdtemp(suffix='.tmp',
                                                  prefix=self._TEST_NAME + '-',
                                                  dir=os.curdir))
    
        # print '%-30s %s\n' % ('running tests in', TestCase.TEST_ROOT)
    
        os.chdir(InTempDir.TEST_ROOT)
        # make a fake bzr directory there to prevent any tests propagating
        # up onto the source directory's real branch
        os.mkdir(os.path.join(InTempDir.TEST_ROOT, '.bzr'))

    def setUp(self):
        super(InTempDir, self).setUp()
        import os
        self._make_test_root()
        self.test_dir = os.path.join(self.TEST_ROOT, self.__class__.__name__)
        os.mkdir(self.test_dir)
        os.chdir(self.test_dir)
        
    def tearDown(self):
        import os
        os.chdir(self.TEST_ROOT)
        super(InTempDir, self).tearDown()


class _MyResult(unittest._TextTestResult):
    """
    Custom TestResult.

    No special behaviour for now.
    """

    def startTest(self, test):
        unittest.TestResult.startTest(self, test)
        # TODO: Maybe show test.shortDescription somewhere?
        what = test.id()
        # python2.3 has the bad habit of just "runit" for doctests
        if what == 'runit':
            what = test.shortDescription()
        if self.showAll:
            self.stream.write('%-60.60s' % what)
        self.stream.flush()

    def addError(self, test, err):
        super(_MyResult, self).addError(test, err)
        self.stream.flush()

    def addFailure(self, test, err):
        super(_MyResult, self).addFailure(test, err)
        self.stream.flush()

    def addSuccess(self, test):
        if self.showAll:
            self.stream.writeln('OK')
        elif self.dots:
            self.stream.write('~')
        self.stream.flush()
        unittest.TestResult.addSuccess(self, test)

    def printErrorList(self, flavour, errors):
        for test, err in errors:
            self.stream.writeln(self.separator1)
            self.stream.writeln("%s: %s" % (flavour,self.getDescription(test)))
            self.stream.writeln(self.separator2)
            self.stream.writeln("%s" % err)
            if isinstance(test, TestCase):
                self.stream.writeln()
                self.stream.writeln('log from this test:')
                print >>self.stream, test._get_log()



class TextTestRunner(unittest.TextTestRunner):

    def __init__(self, stream=sys.stderr, descriptions=0, verbosity=1):
        super(TextTestRunner, self).__init__(stream, descriptions, verbosity)

    def _makeResult(self):
        return _MyResult(self.stream, self.descriptions, self.verbosity)

    # If we want the old 4 line summary output (count, 0 failures, 0 errors)
    # we can override run() too.


def run_suite(suite, name='test', verbose=False):
    import shutil
    InTempDir._TEST_NAME = name
    if verbose:
        verbosity = 2
    else:
        verbosity = 1
    runner = TextTestRunner(stream=sys.stdout, verbosity=verbosity)
    result = runner.run(suite)
    # This is still a little bogus, 
    # but only a little. Folk not using our testrunner will
    # have to delete their temp directories themselves.
    if result.wasSuccessful():
        shutil.rmtree(InTempDir.TEST_ROOT) 
    else:
        print "Failed tests working directories are in '%s'\n" % InTempDir.TEST_ROOT
    return result.wasSuccessful()
