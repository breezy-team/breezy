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




    def log(self, msg):
        """Log a message to a progress file"""
        print >>self.TEST_LOG, msg
               

class InTempDir(TestBase):
    """Base class for tests run in a temporary branch."""
    def setUp(self):
        import os
        self.branch_dir = os.path.join(self.TEST_DIR, self.__class__.__name__)
        os.mkdir(self.branch_dir)
        os.chdir(self.branch_dir)
        
    def tearDown(self):
        import os
        os.chdir(self.TEST_DIR)





class _MyResult(TestResult):
    """
    Custom TestResult.

    No special behaviour for now.
    """
#     def startTest(self, test):
#         print str(test).ljust(50),
#         TestResult.startTest(self, test)

#     def stopTest(self, test):
#         print
#         TestResult.stopTest(self, test)


    pass




def selftest():
    from unittest import TestLoader, TestSuite
    import bzrlib
    import bzrlib.selftest.whitebox
    import bzrlib.selftest.blackbox
    from doctest import DocTestSuite
    import os
    import shutil
    import time

    _setup_test_log()
    _setup_test_dir()

    suite = TestSuite()
    tl = TestLoader()

    for m in bzrlib.selftest.whitebox, :
        suite.addTest(tl.loadTestsFromModule(m))

    suite.addTest(bzrlib.selftest.blackbox.suite())

    for m in bzrlib.store, bzrlib.inventory, bzrlib.branch, bzrlib.osutils, \
            bzrlib.commands:
        suite.addTest(DocTestSuite(m))

    result = _MyResult()
    suite.run(result)

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
    TestBase.TEST_DIR = os.path.abspath("testbzr.tmp")

    print '%-30s %s' % ('running tests in', TestBase.TEST_DIR)

    if os.path.exists(TestBase.TEST_DIR):
        shutil.rmtree(TestBase.TEST_DIR)
    os.mkdir(TestBase.TEST_DIR)
    os.chdir(TestBase.TEST_DIR)

    # make a fake bzr directory there to prevent any tests propagating
    # up onto the source directory's real branch
    os.mkdir(os.path.join(TestBase.TEST_DIR, '.bzr'))

    

def _show_results(result):
     for case, tb in result.errors:
         _show_test_failure('ERROR', case, tb)

     for case, tb in result.failures:
         _show_test_failure('FAILURE', case, tb)
         
     print
     print '%4d tests run' % result.testsRun
     print '%4d errors' % len(result.errors)
     print '%4d failures' % len(result.failures)



def _show_test_failure(kind, case, tb):
     print (kind + '! ').ljust(60, '-')
     print case
     print tb
     print ''.ljust(60, '-')
    
