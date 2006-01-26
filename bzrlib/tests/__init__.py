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


# TODO: Perhaps there should be an API to find out if bzr running under the
# test suite -- some plugins might want to avoid making intrusive changes if
# this is the case.  However, we want behaviour under to test to diverge as
# little as possible, so this should be used rarely if it's added at all.
# (Suggestion from j-a-meinel, 2005-11-24)

from cStringIO import StringIO
import difflib
import errno
import logging
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest
import time
import codecs

import bzrlib.branch
import bzrlib.commands
from bzrlib.errors import BzrError
import bzrlib.inventory
import bzrlib.iterablefile
import bzrlib.merge3
import bzrlib.osutils
import bzrlib.osutils as osutils
import bzrlib.plugin
import bzrlib.store
import bzrlib.trace
from bzrlib.transport import urlescape
from bzrlib.trace import mutter
from bzrlib.tests.TestUtil import TestLoader, TestSuite
from bzrlib.tests.treeshape import build_tree_contents

MODULES_TO_TEST = []
MODULES_TO_DOCTEST = [
                      bzrlib.branch,
                      bzrlib.commands,
                      bzrlib.errors,
                      bzrlib.inventory,
                      bzrlib.iterablefile,
                      bzrlib.merge3,
                      bzrlib.option,
                      bzrlib.osutils,
                      bzrlib.store
                      ]
def packages_to_test():
    import bzrlib.tests.blackbox
    return [
            bzrlib.tests.blackbox
            ]


class _MyResult(unittest._TextTestResult):
    """Custom TestResult.

    Shows output in a different format, including displaying runtime for tests.
    """
    stop_early = False

    def _elapsedTime(self):
        return "%5dms" % (1000 * (time.time() - self._start_time))

    def startTest(self, test):
        unittest.TestResult.startTest(self, test)
        # In a short description, the important words are in
        # the beginning, but in an id, the important words are
        # at the end
        SHOW_DESCRIPTIONS = False
        if self.showAll:
            width = osutils.terminal_width()
            name_width = width - 15
            what = None
            if SHOW_DESCRIPTIONS:
                what = test.shortDescription()
                if what:
                    if len(what) > name_width:
                        what = what[:name_width-3] + '...'
            if what is None:
                what = test.id()
                if what.startswith('bzrlib.tests.'):
                    what = what[13:]
                if len(what) > name_width:
                    what = '...' + what[3-name_width:]
            what = what.ljust(name_width)
            self.stream.write(what)
        self.stream.flush()
        self._start_time = time.time()

    def addError(self, test, err):
        if isinstance(err[1], TestSkipped):
            return self.addSkipped(test, err)    
        unittest.TestResult.addError(self, test, err)
        if self.showAll:
            self.stream.writeln("ERROR %s" % self._elapsedTime())
        elif self.dots:
            self.stream.write('E')
        self.stream.flush()
        if self.stop_early:
            self.stop()

    def addFailure(self, test, err):
        unittest.TestResult.addFailure(self, test, err)
        if self.showAll:
            self.stream.writeln(" FAIL %s" % self._elapsedTime())
        elif self.dots:
            self.stream.write('F')
        self.stream.flush()
        if self.stop_early:
            self.stop()

    def addSuccess(self, test):
        if self.showAll:
            self.stream.writeln('   OK %s' % self._elapsedTime())
        elif self.dots:
            self.stream.write('~')
        self.stream.flush()
        unittest.TestResult.addSuccess(self, test)

    def addSkipped(self, test, skip_excinfo):
        if self.showAll:
            print >>self.stream, ' SKIP %s' % self._elapsedTime()
            print >>self.stream, '     %s' % skip_excinfo[1]
        elif self.dots:
            self.stream.write('S')
        self.stream.flush()
        # seems best to treat this as success from point-of-view of unittest
        # -- it actually does nothing so it barely matters :)
        unittest.TestResult.addSuccess(self, test)

    def printErrorList(self, flavour, errors):
        for test, err in errors:
            self.stream.writeln(self.separator1)
            self.stream.writeln("%s: %s" % (flavour, self.getDescription(test)))
            if hasattr(test, '_get_log'):
                print >>self.stream
                print >>self.stream, \
                        ('vvvv[log from %s]' % test.id()).ljust(78,'-')
                print >>self.stream, test._get_log()
                print >>self.stream, \
                        ('^^^^[log from %s]' % test.id()).ljust(78,'-')
            self.stream.writeln(self.separator2)
            self.stream.writeln("%s" % err)


class TextTestRunner(unittest.TextTestRunner):
    stop_on_failure = False

    def _makeResult(self):
        result = _MyResult(self.stream, self.descriptions, self.verbosity)
        result.stop_early = self.stop_on_failure
        return result


def iter_suite_tests(suite):
    """Return all tests in a suite, recursing through nested suites"""
    for item in suite._tests:
        if isinstance(item, unittest.TestCase):
            yield item
        elif isinstance(item, unittest.TestSuite):
            for r in iter_suite_tests(item):
                yield r
        else:
            raise Exception('unknown object %r inside test suite %r'
                            % (item, suite))


class TestSkipped(Exception):
    """Indicates that a test was intentionally skipped, rather than failing."""
    # XXX: Not used yet


class CommandFailed(Exception):
    pass

class TestCase(unittest.TestCase):
    """Base class for bzr unit tests.
    
    Tests that need access to disk resources should subclass 
    TestCaseInTempDir not TestCase.

    Error and debug log messages are redirected from their usual
    location into a temporary file, the contents of which can be
    retrieved by _get_log().  We use a real OS file, not an in-memory object,
    so that it can also capture file IO.  When the test completes this file
    is read into memory and removed from disk.
       
    There are also convenience functions to invoke bzr's command-line
    routine, and to build and check bzr trees.
   
    In addition to the usual method of overriding tearDown(), this class also
    allows subclasses to register functions into the _cleanups list, which is
    run in order as the object is torn down.  It's less likely this will be
    accidentally overlooked.
    """

    BZRPATH = 'bzr'
    _log_file_name = None
    _log_contents = ''

    def setUp(self):
        unittest.TestCase.setUp(self)
        self._cleanups = []
        self._cleanEnvironment()
        bzrlib.trace.disable_default_logging()
        self._startLogFile()

    def _ndiff_strings(self, a, b):
        """Return ndiff between two strings containing lines.
        
        A trailing newline is added if missing to make the strings
        print properly."""
        if b and b[-1] != '\n':
            b += '\n'
        if a and a[-1] != '\n':
            a += '\n'
        difflines = difflib.ndiff(a.splitlines(True),
                                  b.splitlines(True),
                                  linejunk=lambda x: False,
                                  charjunk=lambda x: False)
        return ''.join(difflines)

    def assertEqualDiff(self, a, b):
        """Assert two texts are equal, if not raise an exception.
        
        This is intended for use with multi-line strings where it can 
        be hard to find the differences by eye.
        """
        # TODO: perhaps override assertEquals to call this for strings?
        if a == b:
            return
        raise AssertionError("texts not equal:\n" + 
                             self._ndiff_strings(a, b))      
        
    def assertStartsWith(self, s, prefix):
        if not s.startswith(prefix):
            raise AssertionError('string %r does not start with %r' % (s, prefix))

    def assertEndsWith(self, s, suffix):
        if not s.endswith(prefix):
            raise AssertionError('string %r does not end with %r' % (s, suffix))

    def assertContainsRe(self, haystack, needle_re):
        """Assert that a contains something matching a regular expression."""
        if not re.search(needle_re, haystack):
            raise AssertionError('pattern "%s" not found in "%s"'
                    % (needle_re, haystack))

    def AssertSubset(self, sublist, superlist):
        """Assert that every entry in sublist is present in superlist."""
        missing = []
        for entry in sublist:
            if entry not in superlist:
                missing.append(entry)
        if len(missing) > 0:
            raise AssertionError("value(s) %r not present in container %r" % 
                                 (missing, superlist))

    def assertIs(self, left, right):
        if not (left is right):
            raise AssertionError("%r is not %r." % (left, right))

    def assertTransportMode(self, transport, path, mode):
        """Fail if a path does not have mode mode.
        
        If modes are not supported on this platform, the test is skipped.
        """
        if sys.platform == 'win32':
            return
        path_stat = transport.stat(path)
        actual_mode = stat.S_IMODE(path_stat.st_mode)
        self.assertEqual(mode, actual_mode,
            'mode of %r incorrect (%o != %o)' % (path, mode, actual_mode))

    def _startLogFile(self):
        """Send bzr and test log messages to a temporary file.

        The file is removed as the test is torn down.
        """
        fileno, name = tempfile.mkstemp(suffix='.log', prefix='testbzr')
        encoder, decoder, stream_reader, stream_writer = codecs.lookup('UTF-8')
        self._log_file = stream_writer(os.fdopen(fileno, 'w+'))
        bzrlib.trace.enable_test_log(self._log_file)
        self._log_file_name = name
        self.addCleanup(self._finishLogFile)

    def _finishLogFile(self):
        """Finished with the log file.

        Read contents into memory, close, and delete.
        """
        bzrlib.trace.disable_test_log()
        self._log_file.seek(0)
        self._log_contents = self._log_file.read()
        self._log_file.close()
        os.remove(self._log_file_name)
        self._log_file = self._log_file_name = None

    def addCleanup(self, callable):
        """Arrange to run a callable when this case is torn down.

        Callables are run in the reverse of the order they are registered, 
        ie last-in first-out.
        """
        if callable in self._cleanups:
            raise ValueError("cleanup function %r already registered on %s" 
                    % (callable, self))
        self._cleanups.append(callable)

    def _cleanEnvironment(self):
        new_env = {
            'HOME': os.getcwd(),
            'APPDATA': os.getcwd(),
            'BZREMAIL': None,
            'EMAIL': None,
        }
        self.__old_env = {}
        self.addCleanup(self._restoreEnvironment)
        for name, value in new_env.iteritems():
            self._captureVar(name, value)


    def _captureVar(self, name, newvalue):
        """Set an environment variable, preparing it to be reset when finished."""
        self.__old_env[name] = os.environ.get(name, None)
        if newvalue is None:
            if name in os.environ:
                del os.environ[name]
        else:
            os.environ[name] = newvalue

    @staticmethod
    def _restoreVar(name, value):
        if value is None:
            if name in os.environ:
                del os.environ[name]
        else:
            os.environ[name] = value

    def _restoreEnvironment(self):
        for name, value in self.__old_env.iteritems():
            self._restoreVar(name, value)

    def tearDown(self):
        self._runCleanups()
        unittest.TestCase.tearDown(self)

    def _runCleanups(self):
        """Run registered cleanup functions. 

        This should only be called from TestCase.tearDown.
        """
        # TODO: Perhaps this should keep running cleanups even if 
        # one of them fails?
        for cleanup_fn in reversed(self._cleanups):
            cleanup_fn()

    def log(self, *args):
        mutter(*args)

    def _get_log(self):
        """Return as a string the log for this test"""
        if self._log_file_name:
            return open(self._log_file_name).read()
        else:
            return self._log_contents
        # TODO: Delete the log after it's been read in

    def capture(self, cmd, retcode=0):
        """Shortcut that splits cmd into words, runs, and returns stdout"""
        return self.run_bzr_captured(cmd.split(), retcode=retcode)[0]

    def run_bzr_captured(self, argv, retcode=0):
        """Invoke bzr and return (stdout, stderr).

        Useful for code that wants to check the contents of the
        output, the way error messages are presented, etc.

        This should be the main method for tests that want to exercise the
        overall behavior of the bzr application (rather than a unit test
        or a functional test of the library.)

        Much of the old code runs bzr by forking a new copy of Python, but
        that is slower, harder to debug, and generally not necessary.

        This runs bzr through the interface that catches and reports
        errors, and with logging set to something approximating the
        default, so that error reporting can be checked.

        argv -- arguments to invoke bzr
        retcode -- expected return code, or None for don't-care.
        """
        stdout = StringIO()
        stderr = StringIO()
        self.log('run bzr: %s', ' '.join(argv))
        # FIXME: don't call into logging here
        handler = logging.StreamHandler(stderr)
        handler.setFormatter(bzrlib.trace.QuietFormatter())
        handler.setLevel(logging.INFO)
        logger = logging.getLogger('')
        logger.addHandler(handler)
        try:
            result = self.apply_redirected(None, stdout, stderr,
                                           bzrlib.commands.run_bzr_catch_errors,
                                           argv)
        finally:
            logger.removeHandler(handler)
        out = stdout.getvalue()
        err = stderr.getvalue()
        if out:
            self.log('output:\n%s', out)
        if err:
            self.log('errors:\n%s', err)
        if retcode is not None:
            self.assertEquals(result, retcode)
        return out, err

    def run_bzr(self, *args, **kwargs):
        """Invoke bzr, as if it were run from the command line.

        This should be the main method for tests that want to exercise the
        overall behavior of the bzr application (rather than a unit test
        or a functional test of the library.)

        This sends the stdout/stderr results into the test's log,
        where it may be useful for debugging.  See also run_captured.
        """
        retcode = kwargs.pop('retcode', 0)
        return self.run_bzr_captured(args, retcode)

    def check_inventory_shape(self, inv, shape):
        """Compare an inventory to a list of expected names.

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
        if not callable(a_callable):
            raise ValueError("a_callable must be callable.")
        if stdin is None:
            stdin = StringIO("")
        if stdout is None:
            if hasattr(self, "_log_file"):
                stdout = self._log_file
            else:
                stdout = StringIO()
        if stderr is None:
            if hasattr(self, "_log_file"):
                stderr = self._log_file
            else:
                stderr = StringIO()
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
            self.fail("contents of %s not as expected" % filename)

    def _make_test_root(self):
        if TestCaseInTempDir.TEST_ROOT is not None:
            return
        i = 0
        while True:
            root = u'test%04d.tmp' % i
            try:
                os.mkdir(root)
            except OSError, e:
                if e.errno == errno.EEXIST:
                    i += 1
                    continue
                else:
                    raise
            # successfully created
            TestCaseInTempDir.TEST_ROOT = osutils.abspath(root)
            break
        # make a fake bzr directory there to prevent any tests propagating
        # up onto the source directory's real branch
        os.mkdir(osutils.pathjoin(TestCaseInTempDir.TEST_ROOT, '.bzr'))

    def setUp(self):
        super(TestCaseInTempDir, self).setUp()
        self._make_test_root()
        _currentdir = os.getcwdu()
        short_id = self.id().replace('bzrlib.tests.', '') \
                   .replace('__main__.', '')
        self.test_dir = osutils.pathjoin(self.TEST_ROOT, short_id)
        os.mkdir(self.test_dir)
        os.chdir(self.test_dir)
        os.environ['HOME'] = self.test_dir
        os.environ['APPDATA'] = self.test_dir
        def _leaveDirectory():
            os.chdir(_currentdir)
        self.addCleanup(_leaveDirectory)
        
    def build_tree(self, shape, line_endings='native', transport=None):
        """Build a test tree according to a pattern.

        shape is a sequence of file specifications.  If the final
        character is '/', a directory is created.

        This doesn't add anything to a branch.
        :param line_endings: Either 'binary' or 'native'
                             in binary mode, exact contents are written
                             in native mode, the line endings match the
                             default platform endings.

        :param transport: A transport to write to, for building trees on 
                          VFS's. If the transport is readonly or None,
                          "." is opened automatically.
        """
        # XXX: It's OK to just create them using forward slashes on windows?
        if transport is None or transport.is_readonly():
            transport = bzrlib.transport.get_transport(".")
        for name in shape:
            self.assert_(isinstance(name, basestring))
            if name[-1] == '/':
                transport.mkdir(urlescape(name[:-1]))
            else:
                if line_endings == 'binary':
                    end = '\n'
                elif line_endings == 'native':
                    end = os.linesep
                else:
                    raise BzrError('Invalid line ending request %r' % (line_endings,))
                content = "contents of %s%s" % (name, end)
                transport.put(urlescape(name), StringIO(content))

    def build_tree_contents(self, shape):
        build_tree_contents(shape)

    def failUnlessExists(self, path):
        """Fail unless path, which may be abs or relative, exists."""
        self.failUnless(osutils.lexists(path))

    def failIfExists(self, path):
        """Fail if path, which may be abs or relative, exists."""
        self.failIf(osutils.lexists(path))
        
    def assertFileEqual(self, content, path):
        """Fail if path does not contain 'content'."""
        self.failUnless(osutils.lexists(path))
        self.assertEqualDiff(content, open(path, 'r').read())


def filter_suite_by_re(suite, pattern):
    result = TestSuite()
    filter_re = re.compile(pattern)
    for test in iter_suite_tests(suite):
        if filter_re.search(test.id()):
            result.addTest(test)
    return result


def run_suite(suite, name='test', verbose=False, pattern=".*",
              stop_on_failure=False, keep_output=False):
    TestCaseInTempDir._TEST_NAME = name
    if verbose:
        verbosity = 2
    else:
        verbosity = 1
    runner = TextTestRunner(stream=sys.stdout,
                            descriptions=0,
                            verbosity=verbosity)
    runner.stop_on_failure=stop_on_failure
    if pattern != '.*':
        suite = filter_suite_by_re(suite, pattern)
    result = runner.run(suite)
    # This is still a little bogus, 
    # but only a little. Folk not using our testrunner will
    # have to delete their temp directories themselves.
    if result.wasSuccessful() or not keep_output:
        if TestCaseInTempDir.TEST_ROOT is not None:
            shutil.rmtree(TestCaseInTempDir.TEST_ROOT) 
    else:
        print "Failed tests working directories are in '%s'\n" % TestCaseInTempDir.TEST_ROOT
    return result.wasSuccessful()


def selftest(verbose=False, pattern=".*", stop_on_failure=True,
             keep_output=False):
    """Run the whole test suite under the enhanced runner"""
    return run_suite(test_suite(), 'testbzr', verbose=verbose, pattern=pattern,
                     stop_on_failure=stop_on_failure, keep_output=keep_output)


def test_suite():
    """Build and return TestSuite for the whole program."""
    from doctest import DocTestSuite

    global MODULES_TO_DOCTEST

    testmod_names = [ \
                   'bzrlib.tests.test_ancestry',
                   'bzrlib.tests.test_annotate',
                   'bzrlib.tests.test_api',
                   'bzrlib.tests.test_bad_files',
                   'bzrlib.tests.test_basis_inventory',
                   'bzrlib.tests.test_branch',
                   'bzrlib.tests.test_command',
                   'bzrlib.tests.test_commit',
                   'bzrlib.tests.test_commit_merge',
                   'bzrlib.tests.test_config',
                   'bzrlib.tests.test_conflicts',
                   'bzrlib.tests.test_diff',
                   'bzrlib.tests.test_decorators',
                   'bzrlib.tests.test_fetch',
                   'bzrlib.tests.test_fileid_involved',
                   'bzrlib.tests.test_gpg',
                   'bzrlib.tests.test_graph',
                   'bzrlib.tests.test_hashcache',
                   'bzrlib.tests.test_http',
                   'bzrlib.tests.test_identitymap',
                   'bzrlib.tests.test_inv',
                   'bzrlib.tests.test_lockable_files',
                   'bzrlib.tests.test_log',
                   'bzrlib.tests.test_merge',
                   'bzrlib.tests.test_merge3',
                   'bzrlib.tests.test_merge_core',
                   'bzrlib.tests.test_missing',
                   'bzrlib.tests.test_msgeditor',
                   'bzrlib.tests.test_nonascii',
                   'bzrlib.tests.test_options',
                   'bzrlib.tests.test_osutils',
                   'bzrlib.tests.test_parent',
                   'bzrlib.tests.test_permissions',
                   'bzrlib.tests.test_plugins',
                   'bzrlib.tests.test_remove',
                   'bzrlib.tests.test_revision',
                   'bzrlib.tests.test_revisionnamespaces',
                   'bzrlib.tests.test_revprops',
                   'bzrlib.tests.test_reweave',
                   'bzrlib.tests.test_rio',
                   'bzrlib.tests.test_sampler',
                   'bzrlib.tests.test_selftest',
                   'bzrlib.tests.test_setup',
                   'bzrlib.tests.test_sftp_transport',
                   'bzrlib.tests.test_smart_add',
                   'bzrlib.tests.test_source',
                   'bzrlib.tests.test_status',
                   'bzrlib.tests.test_store',
                   'bzrlib.tests.test_symbol_versioning',
                   'bzrlib.tests.test_testament',
                   'bzrlib.tests.test_trace',
                   'bzrlib.tests.test_transactions',
                   'bzrlib.tests.test_transport',
                   'bzrlib.tests.test_tsort',
                   'bzrlib.tests.test_ui',
                   'bzrlib.tests.test_uncommit',
                   'bzrlib.tests.test_upgrade',
                   'bzrlib.tests.test_weave',
                   'bzrlib.tests.test_whitebox',
                   'bzrlib.tests.test_workingtree',
                   'bzrlib.tests.test_xml',
                   ]
    test_transport_implementations = [
        'bzrlib.tests.test_transport_implementations']

    TestCase.BZRPATH = osutils.pathjoin(
            osutils.realpath(osutils.dirname(bzrlib.__path__[0])), 'bzr')
    print '%10s: %s' % ('bzr', osutils.realpath(sys.argv[0]))
    print '%10s: %s' % ('bzrlib', bzrlib.__path__[0])
    print
    suite = TestSuite()
    # python2.4's TestLoader.loadTestsFromNames gives very poor 
    # errors if it fails to load a named module - no indication of what's
    # actually wrong, just "no such module".  We should probably override that
    # class, but for the moment just load them ourselves. (mbp 20051202)
    loader = TestLoader()
    from bzrlib.transport import TransportTestProviderAdapter
    adapter = TransportTestProviderAdapter()
    for mod_name in test_transport_implementations:
        mod = _load_module_by_name(mod_name)
        for test in iter_suite_tests(loader.loadTestsFromModule(mod)):
            suite.addTests(adapter.adapt(test))
    for mod_name in testmod_names:
        mod = _load_module_by_name(mod_name)
        suite.addTest(loader.loadTestsFromModule(mod))
    for package in packages_to_test():
        suite.addTest(package.test_suite())
    for m in MODULES_TO_TEST:
        suite.addTest(loader.loadTestsFromModule(m))
    for m in (MODULES_TO_DOCTEST):
        suite.addTest(DocTestSuite(m))
    for name, plugin in bzrlib.plugin.all_plugins().items():
        if hasattr(plugin, 'test_suite'):
            suite.addTest(plugin.test_suite())
    return suite


def _load_module_by_name(mod_name):
    parts = mod_name.split('.')
    module = __import__(mod_name)
    del parts[0]
    # for historical reasons python returns the top-level module even though
    # it loads the submodule; we need to walk down to get the one we want.
    while parts:
        module = getattr(module, parts.pop(0))
    return module
