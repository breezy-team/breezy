# Copyright (C) 2005 by Canonical Ltd
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

"""Tests for the osutils wrapper."""

import errno
import os
import socket
import stat
import sys

import bzrlib
from bzrlib.errors import BzrBadParameterNotUnicode, InvalidURL
import bzrlib.osutils as osutils
from bzrlib.tests import (
        StringIOWrapper,
        TestCase, 
        TestCaseInTempDir, 
        TestSkipped,
        )


class TestOSUtils(TestCaseInTempDir):

    def test_fancy_rename(self):
        # This should work everywhere
        def rename(a, b):
            osutils.fancy_rename(a, b,
                    rename_func=os.rename,
                    unlink_func=os.unlink)

        open('a', 'wb').write('something in a\n')
        rename('a', 'b')
        self.failIfExists('a')
        self.failUnlessExists('b')
        self.check_file_contents('b', 'something in a\n')

        open('a', 'wb').write('new something in a\n')
        rename('b', 'a')

        self.check_file_contents('a', 'something in a\n')

    def test_rename(self):
        # Rename should be semi-atomic on all platforms
        open('a', 'wb').write('something in a\n')
        osutils.rename('a', 'b')
        self.failIfExists('a')
        self.failUnlessExists('b')
        self.check_file_contents('b', 'something in a\n')

        open('a', 'wb').write('new something in a\n')
        osutils.rename('b', 'a')

        self.check_file_contents('a', 'something in a\n')

    # TODO: test fancy_rename using a MemoryTransport

    def test_01_rand_chars_empty(self):
        result = osutils.rand_chars(0)
        self.assertEqual(result, '')

    def test_02_rand_chars_100(self):
        result = osutils.rand_chars(100)
        self.assertEqual(len(result), 100)
        self.assertEqual(type(result), str)
        self.assertContainsRe(result, r'^[a-z0-9]{100}$')


    def test_rmtree(self):
        # Check to remove tree with read-only files/dirs
        os.mkdir('dir')
        f = file('dir/file', 'w')
        f.write('spam')
        f.close()
        # would like to also try making the directory readonly, but at the
        # moment python shutil.rmtree doesn't handle that properly - it would
        # need to chmod the directory before removing things inside it - deferred
        # for now -- mbp 20060505
        # osutils.make_readonly('dir')
        osutils.make_readonly('dir/file')

        osutils.rmtree('dir')

        self.failIfExists('dir/file')
        self.failIfExists('dir')

    def test_file_kind(self):
        self.build_tree(['file', 'dir/'])
        self.assertEquals('file', osutils.file_kind('file'))
        self.assertEquals('directory', osutils.file_kind('dir/'))
        if osutils.has_symlinks():
            os.symlink('symlink', 'symlink')
            self.assertEquals('symlink', osutils.file_kind('symlink'))
        
        # TODO: jam 20060529 Test a block device
        try:
            os.lstat('/dev/null')
        except OSError, e:
            if e.errno not in (errno.ENOENT,):
                raise
        else:
            self.assertEquals('chardev', osutils.file_kind('/dev/null'))

        mkfifo = getattr(os, 'mkfifo', None)
        if mkfifo:
            mkfifo('fifo')
            try:
                self.assertEquals('fifo', osutils.file_kind('fifo'))
            finally:
                os.remove('fifo')

        AF_UNIX = getattr(socket, 'AF_UNIX', None)
        if AF_UNIX:
            s = socket.socket(AF_UNIX)
            s.bind('socket')
            try:
                self.assertEquals('socket', osutils.file_kind('socket'))
            finally:
                os.remove('socket')

    def test_get_umask(self):
        if sys.platform == 'win32':
            # umask always returns '0', no way to set it
            self.assertEqual(0, osutils.get_umask())
            return

        orig_umask = osutils.get_umask()
        try:
            os.umask(0222)
            self.assertEqual(0222, osutils.get_umask())
            os.umask(0022)
            self.assertEqual(0022, osutils.get_umask())
            os.umask(0002)
            self.assertEqual(0002, osutils.get_umask())
            os.umask(0027)
            self.assertEqual(0027, osutils.get_umask())
        finally:
            os.umask(orig_umask)


class TestSafeUnicode(TestCase):

    def test_from_ascii_string(self):
        self.assertEqual(u'foobar', osutils.safe_unicode('foobar'))

    def test_from_unicode_string_ascii_contents(self):
        self.assertEqual(u'bargam', osutils.safe_unicode(u'bargam'))

    def test_from_unicode_string_unicode_contents(self):
        self.assertEqual(u'bargam\xae', osutils.safe_unicode(u'bargam\xae'))

    def test_from_utf8_string(self):
        self.assertEqual(u'foo\xae', osutils.safe_unicode('foo\xc2\xae'))

    def test_bad_utf8_string(self):
        self.assertRaises(BzrBadParameterNotUnicode,
                          osutils.safe_unicode,
                          '\xbb\xbb')


class TestWin32Funcs(TestCase):
    """Test that the _win32 versions of os utilities return appropriate paths."""

    def test_abspath(self):
        self.assertEqual('C:/foo', osutils._win32_abspath('C:\\foo'))
        self.assertEqual('C:/foo', osutils._win32_abspath('C:/foo'))

    def test_realpath(self):
        self.assertEqual('C:/foo', osutils._win32_realpath('C:\\foo'))
        self.assertEqual('C:/foo', osutils._win32_realpath('C:/foo'))

    def test_pathjoin(self):
        self.assertEqual('path/to/foo', osutils._win32_pathjoin('path', 'to', 'foo'))
        self.assertEqual('C:/foo', osutils._win32_pathjoin('path\\to', 'C:\\foo'))
        self.assertEqual('C:/foo', osutils._win32_pathjoin('path/to', 'C:/foo'))
        self.assertEqual('path/to/foo', osutils._win32_pathjoin('path/to/', 'foo'))
        self.assertEqual('/foo', osutils._win32_pathjoin('C:/path/to/', '/foo'))
        self.assertEqual('/foo', osutils._win32_pathjoin('C:\\path\\to\\', '\\foo'))

    def test_normpath(self):
        self.assertEqual('path/to/foo', osutils._win32_normpath(r'path\\from\..\to\.\foo'))
        self.assertEqual('path/to/foo', osutils._win32_normpath('path//from/../to/./foo'))

    def test_getcwd(self):
        cwd = osutils._win32_getcwd()
        os_cwd = os.getcwdu()
        self.assertEqual(os_cwd[1:].replace('\\', '/'), cwd[1:])
        # win32 is inconsistent whether it returns lower or upper case
        # and even if it was consistent the user might type the other
        # so we force it to uppercase
        # running python.exe under cmd.exe return capital C:\\
        # running win32 python inside a cygwin shell returns lowercase
        self.assertEqual(os_cwd[0].upper(), cwd[0])

    def test_fixdrive(self):
        self.assertEqual('H:/foo', osutils._win32_fixdrive('h:/foo'))
        self.assertEqual('H:/foo', osutils._win32_fixdrive('H:/foo'))
        self.assertEqual('C:\\foo', osutils._win32_fixdrive('c:\\foo'))


class TestWin32FuncsDirs(TestCaseInTempDir):
    """Test win32 functions that create files."""
    
    def test_getcwd(self):
        # Make sure getcwd can handle unicode filenames
        try:
            os.mkdir(u'mu-\xb5')
        except UnicodeError:
            raise TestSkipped("Unable to create Unicode filename")

        os.chdir(u'mu-\xb5')
        # TODO: jam 20060427 This will probably fail on Mac OSX because
        #       it will change the normalization of B\xe5gfors
        #       Consider using a different unicode character, or make
        #       osutils.getcwd() renormalize the path.
        self.assertEndsWith(osutils._win32_getcwd(), u'mu-\xb5')

    def test_mkdtemp(self):
        tmpdir = osutils._win32_mkdtemp(dir='.')
        self.assertFalse('\\' in tmpdir)

    def test_rename(self):
        a = open('a', 'wb')
        a.write('foo\n')
        a.close()
        b = open('b', 'wb')
        b.write('baz\n')
        b.close()

        osutils._win32_rename('b', 'a')
        self.failUnlessExists('a')
        self.failIfExists('b')
        self.assertFileEqual('baz\n', 'a')

    def test_rename_missing_file(self):
        a = open('a', 'wb')
        a.write('foo\n')
        a.close()

        try:
            osutils._win32_rename('b', 'a')
        except (IOError, OSError), e:
            self.assertEqual(errno.ENOENT, e.errno)
        self.assertFileEqual('foo\n', 'a')

    def test_rename_missing_dir(self):
        os.mkdir('a')
        try:
            osutils._win32_rename('b', 'a')
        except (IOError, OSError), e:
            self.assertEqual(errno.ENOENT, e.errno)

    def test_rename_current_dir(self):
        os.mkdir('a')
        os.chdir('a')
        # You can't rename the working directory
        # doing rename non-existant . usually
        # just raises ENOENT, since non-existant
        # doesn't exist.
        try:
            osutils._win32_rename('b', '.')
        except (IOError, OSError), e:
            self.assertEqual(errno.ENOENT, e.errno)


class TestMacFuncsDirs(TestCaseInTempDir):
    """Test mac special functions that require directories."""

    def test_getcwd(self):
        # On Mac, this will actually create Ba\u030agfors
        # but chdir will still work, because it accepts both paths
        try:
            os.mkdir(u'B\xe5gfors')
        except UnicodeError:
            raise TestSkipped("Unable to create Unicode filename")

        os.chdir(u'B\xe5gfors')
        self.assertEndsWith(osutils._mac_getcwd(), u'B\xe5gfors')

    def test_getcwd_nonnorm(self):
        # Test that _mac_getcwd() will normalize this path
        try:
            os.mkdir(u'Ba\u030agfors')
        except UnicodeError:
            raise TestSkipped("Unable to create Unicode filename")

        os.chdir(u'Ba\u030agfors')
        self.assertEndsWith(osutils._mac_getcwd(), u'B\xe5gfors')

class TestSplitLines(TestCase):

    def test_split_unicode(self):
        self.assertEqual([u'foo\n', u'bar\xae'],
                         osutils.split_lines(u'foo\nbar\xae'))
        self.assertEqual([u'foo\n', u'bar\xae\n'],
                         osutils.split_lines(u'foo\nbar\xae\n'))

    def test_split_with_carriage_returns(self):
        self.assertEqual(['foo\rbar\n'],
                         osutils.split_lines('foo\rbar\n'))


class TestWalkDirs(TestCaseInTempDir):

    def test_walkdirs(self):
        tree = [
            '.bzr',
            '0file',
            '1dir/',
            '1dir/0file',
            '1dir/1dir/',
            '2file'
            ]
        self.build_tree(tree)
        expected_dirblocks = [
                (('', '.'),
                 [('0file', '0file', 'file'),
                  ('1dir', '1dir', 'directory'),
                  ('2file', '2file', 'file'),
                 ]
                ),
                (('1dir', './1dir'),
                 [('1dir/0file', '0file', 'file'),
                  ('1dir/1dir', '1dir', 'directory'),
                 ]
                ),
                (('1dir/1dir', './1dir/1dir'),
                 [
                 ]
                ),
            ]
        result = []
        found_bzrdir = False
        for dirdetail, dirblock in osutils.walkdirs('.'):
            if len(dirblock) and dirblock[0][1] == '.bzr':
                # this tests the filtering of selected paths
                found_bzrdir = True
                del dirblock[0]
            result.append((dirdetail, dirblock))

        self.assertTrue(found_bzrdir)
        self.assertEqual(expected_dirblocks,
            [(dirinfo, [line[0:3] for line in block]) for dirinfo, block in result])
        # you can search a subdir only, with a supplied prefix.
        result = []
        for dirblock in osutils.walkdirs('./1dir', '1dir'):
            result.append(dirblock)
        self.assertEqual(expected_dirblocks[1:],
            [(dirinfo, [line[0:3] for line in block]) for dirinfo, block in result])

    def assertPathCompare(self, path_less, path_greater):
        """check that path_less and path_greater compare correctly."""
        self.assertEqual(0, osutils.compare_paths_prefix_order(
            path_less, path_less))
        self.assertEqual(0, osutils.compare_paths_prefix_order(
            path_greater, path_greater))
        self.assertEqual(-1, osutils.compare_paths_prefix_order(
            path_less, path_greater))
        self.assertEqual(1, osutils.compare_paths_prefix_order(
            path_greater, path_less))

    def test_compare_paths_prefix_order(self):
        # root before all else
        self.assertPathCompare("/", "/a")
        # alpha within a dir
        self.assertPathCompare("/a", "/b")
        self.assertPathCompare("/b", "/z")
        # high dirs before lower.
        self.assertPathCompare("/z", "/a/a")
        # except if the deeper dir should be output first
        self.assertPathCompare("/a/b/c", "/d/g")
        # lexical betwen dirs of the same height
        self.assertPathCompare("/a/z", "/z/z")
        self.assertPathCompare("/a/c/z", "/a/d/e")

        # this should also be consistent for no leading / paths
        # root before all else
        self.assertPathCompare("", "a")
        # alpha within a dir
        self.assertPathCompare("a", "b")
        self.assertPathCompare("b", "z")
        # high dirs before lower.
        self.assertPathCompare("z", "a/a")
        # except if the deeper dir should be output first
        self.assertPathCompare("a/b/c", "d/g")
        # lexical betwen dirs of the same height
        self.assertPathCompare("a/z", "z/z")
        self.assertPathCompare("a/c/z", "a/d/e")

    def test_path_prefix_sorting(self):
        """Doing a sort on path prefix should match our sample data."""
        original_paths = [
            'a',
            'a/b',
            'a/b/c',
            'b',
            'b/c',
            'd',
            'd/e',
            'd/e/f',
            'd/f',
            'd/g',
            'g',
            ]

        dir_sorted_paths = [
            'a',
            'b',
            'd',
            'g',
            'a/b',
            'a/b/c',
            'b/c',
            'd/e',
            'd/f',
            'd/g',
            'd/e/f',
            ]

        self.assertEqual(
            dir_sorted_paths,
            sorted(original_paths, key=osutils.path_prefix_key))
        # using the comparison routine shoudl work too:
        self.assertEqual(
            dir_sorted_paths,
            sorted(original_paths, cmp=osutils.compare_paths_prefix_order))


class TestCopyTree(TestCaseInTempDir):
    
    def test_copy_basic_tree(self):
        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c'])
        osutils.copy_tree('source', 'target')
        self.assertEqual(['a', 'b'], os.listdir('target'))
        self.assertEqual(['c'], os.listdir('target/b'))

    def test_copy_tree_target_exists(self):
        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c',
                         'target/'])
        osutils.copy_tree('source', 'target')
        self.assertEqual(['a', 'b'], os.listdir('target'))
        self.assertEqual(['c'], os.listdir('target/b'))

    def test_copy_tree_symlinks(self):
        if not osutils.has_symlinks():
            return
        self.build_tree(['source/'])
        os.symlink('a/generic/path', 'source/lnk')
        osutils.copy_tree('source', 'target')
        self.assertEqual(['lnk'], os.listdir('target'))
        self.assertEqual('a/generic/path', os.readlink('target/lnk'))

    def test_copy_tree_handlers(self):
        processed_files = []
        processed_links = []
        def file_handler(from_path, to_path):
            processed_files.append(('f', from_path, to_path))
        def dir_handler(from_path, to_path):
            processed_files.append(('d', from_path, to_path))
        def link_handler(from_path, to_path):
            processed_links.append((from_path, to_path))
        handlers = {'file':file_handler,
                    'directory':dir_handler,
                    'symlink':link_handler,
                   }

        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c'])
        if osutils.has_symlinks():
            os.symlink('a/generic/path', 'source/lnk')
        osutils.copy_tree('source', 'target', handlers=handlers)

        self.assertEqual([('d', 'source', 'target'),
                          ('f', 'source/a', 'target/a'),
                          ('d', 'source/b', 'target/b'),
                          ('f', 'source/b/c', 'target/b/c'),
                         ], processed_files)
        self.failIfExists('target')
        if osutils.has_symlinks():
            self.assertEqual([('source/lnk', 'target/lnk')], processed_links)


class TestTerminalEncoding(TestCase):
    """Test the auto-detection of proper terminal encoding."""

    def setUp(self):
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        self._stdin = sys.stdin
        self._user_encoding = bzrlib.user_encoding

        self.addCleanup(self._reset)

        sys.stdout = StringIOWrapper()
        sys.stdout.encoding = 'stdout_encoding'
        sys.stderr = StringIOWrapper()
        sys.stderr.encoding = 'stderr_encoding'
        sys.stdin = StringIOWrapper()
        sys.stdin.encoding = 'stdin_encoding'
        bzrlib.user_encoding = 'user_encoding'

    def _reset(self):
        sys.stdout = self._stdout
        sys.stderr = self._stderr
        sys.stdin = self._stdin
        bzrlib.user_encoding = self._user_encoding

    def test_get_terminal_encoding(self):
        # first preference is stdout encoding
        self.assertEqual('stdout_encoding', osutils.get_terminal_encoding())

        sys.stdout.encoding = None
        # if sys.stdout is None, fall back to sys.stdin
        self.assertEqual('stdin_encoding', osutils.get_terminal_encoding())

        sys.stdin.encoding = None
        # and in the worst case, use bzrlib.user_encoding
        self.assertEqual('user_encoding', osutils.get_terminal_encoding())

