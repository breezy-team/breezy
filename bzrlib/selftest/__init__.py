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


from unittest import TestResult, TestCase

try:
    import shutil
    from subprocess import call, Popen, PIPE
except ImportError, e:
    sys.stderr.write("testbzr: sorry, this test suite requires the subprocess module\n"
                     "this is shipped with python2.4 and available separately for 2.3\n")
    raise


class CommandFailed(Exception):
    pass


class TestBase(TestCase):
    """Base class for bzr test cases.

    Just defines some useful helper functions; doesn't actually test
    anything.
    """
    
    # TODO: Special methods to invoke bzr, so that we can run it
    # through a specified Python intepreter

    OVERRIDE_PYTHON = None # to run with alternative python 'python'
    BZRPATH = 'bzr'

    _log_buf = ""


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
        cmd = self.formcmd(cmd)

        self.log('$ ' + ' '.join(cmd))
        actual_retcode = call(cmd, stdout=self.TEST_LOG, stderr=self.TEST_LOG)

        if retcode != actual_retcode:
            raise CommandFailed("test failed: %r returned %d, expected %d"
                                % (cmd, actual_retcode, retcode))


    def backtick(self, cmd, retcode=0):
        """Run a command and return its output"""
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
            self.log("expected: %r" % expected)
            self.log("actually: %r" % contents)
            self.fail("contents of %s not as expected")
            


class InTempDir(TestBase):
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
    def __init__(self, out):
        self.out = out
        TestResult.__init__(self)

    def startTest(self, test):
        # TODO: Maybe show test.shortDescription somewhere?
        print >>self.out, '%-60.60s' % test.id(),
        self.out.flush()
        TestResult.startTest(self, test)

    def stopTest(self, test):
        # print
        TestResult.stopTest(self, test)


    def addError(self, test, err):
        print >>self.out, 'ERROR'
        TestResult.addError(self, test, err)
        _show_test_failure('error', test, err, self.out)

    def addFailure(self, test, err):
        print >>self.out, 'FAILURE'
        TestResult.addFailure(self, test, err)
        _show_test_failure('failure', test, err, self.out)

    def addSuccess(self, test):
        print >>self.out, 'OK'
        TestResult.addSuccess(self, test)



def selftest():
    from unittest import TestLoader, TestSuite
    import bzrlib, bzrlib.store, bzrlib.inventory, bzrlib.branch, bzrlib.osutils, bzrlib.commands

    import bzrlib.selftest.whitebox
    import bzrlib.selftest.blackbox
    import bzrlib.selftest.versioning
    import bzrlib.selftest.merge3
    import bzrlib.merge_core
    from doctest import DocTestSuite
    import os
    import shutil
    import time
    import sys

    TestBase.BZRPATH = os.path.join(os.path.realpath(os.path.dirname(bzrlib.__path__[0])), 'bzr')
    print '%-30s %s' % ('bzr binary', TestBase.BZRPATH)

    _setup_test_log()
    _setup_test_dir()
    print

    suite = TestSuite()
    tl = TestLoader()

    # should also test bzrlib.merge_core, but they seem to be out of date with
    # the code.

    for m in bzrlib.selftest.whitebox, \
            bzrlib.selftest.versioning, \
            bzrlib.selftest.merge3:
        suite.addTest(tl.loadTestsFromModule(m))

    for m in bzrlib.store, bzrlib.inventory, bzrlib.branch, bzrlib.osutils, \
            bzrlib.commands, \
            bzrlib.merge3:
        suite.addTest(DocTestSuite(m))

    suite.addTest(bzrlib.selftest.blackbox.suite())

    # save stdout & stderr so there's no leakage from code-under-test
    real_stdout = sys.stdout
    real_stderr = sys.stderr
    sys.stdout = sys.stderr = TestBase.TEST_LOG
    try:
        result = _MyResult(real_stdout)
        suite.run(result)
    finally:
        sys.stdout = real_stdout
        sys.stderr = real_stderr

    _show_results(result)

    return result.wasSuccessful()




def _setup_test_log():
    import time
    import os
    
    log_filename = os.path.abspath('testbzr.log')
    TestBase.TEST_LOG = open(log_filename, 'wt', buffering=1) # line buffered

    print >>TestBase.TEST_LOG, "bzr tests run at " + time.ctime()
    print '%-30s %s' % ('test log', log_filename)


def _setup_test_dir():
    import os
    import shutil
    
    TestBase.ORIG_DIR = os.getcwdu()
    TestBase.TEST_ROOT = os.path.abspath("testbzr.tmp")

    print '%-30s %s' % ('running tests in', TestBase.TEST_ROOT)

    if os.path.exists(TestBase.TEST_ROOT):
        shutil.rmtree(TestBase.TEST_ROOT)
    os.mkdir(TestBase.TEST_ROOT)
    os.chdir(TestBase.TEST_ROOT)

    # make a fake bzr directory there to prevent any tests propagating
    # up onto the source directory's real branch
    os.mkdir(os.path.join(TestBase.TEST_ROOT, '.bzr'))

    

def _show_results(result):
     print
     print '%4d tests run' % result.testsRun
     print '%4d errors' % len(result.errors)
     print '%4d failures' % len(result.failures)



def _show_test_failure(kind, case, exc_info, out):
    from traceback import print_exception
    
    print >>out, '-' * 60
    print >>out, case
    
    desc = case.shortDescription()
    if desc:
        print >>out, '   (%s)' % desc
         
    print_exception(exc_info[0], exc_info[1], exc_info[2], None, out)
        
    if isinstance(case, TestBase):
        print >>out
        print >>out, 'log from this test:'
        print >>out, case._log_buf
         
    print >>out, '-' * 60
    

