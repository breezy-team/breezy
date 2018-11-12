# Copyright (C) 2010 Canonical Ltd
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

import os
import sys
import tempfile

from .. import (
    mergetools,
    tests
)


class TestFilenameSubstitution(tests.TestCaseInTempDir):

    def test_simple_filename(self):
        cmd_list = ['kdiff3', '{base}', '{this}', '{other}', '-o', '{result}']
        args, tmpfile = mergetools._subst_filename(cmd_list, 'test.txt')
        self.assertEqual(
            ['kdiff3',
             'test.txt.BASE',
             'test.txt.THIS',
             'test.txt.OTHER',
             '-o',
             'test.txt'],
            args)

    def test_spaces(self):
        cmd_list = ['kdiff3', '{base}', '{this}', '{other}', '-o', '{result}']
        args, tmpfile = mergetools._subst_filename(cmd_list,
                                                   'file with space.txt')
        self.assertEqual(
            ['kdiff3',
             'file with space.txt.BASE',
             'file with space.txt.THIS',
             'file with space.txt.OTHER',
             '-o',
             'file with space.txt'],
            args)

    def test_spaces_and_quotes(self):
        cmd_list = ['kdiff3', '{base}', '{this}', '{other}', '-o', '{result}']
        args, tmpfile = mergetools._subst_filename(
            cmd_list, 'file with "space and quotes".txt')
        self.assertEqual(
            ['kdiff3',
             'file with "space and quotes".txt.BASE',
             'file with "space and quotes".txt.THIS',
             'file with "space and quotes".txt.OTHER',
             '-o',
             'file with "space and quotes".txt'],
            args)

    def test_tempfile(self):
        self.build_tree(('test.txt', 'test.txt.BASE', 'test.txt.THIS',
                         'test.txt.OTHER'))
        cmd_list = ['some_tool', '{this_temp}']
        args, tmpfile = mergetools._subst_filename(cmd_list, 'test.txt')
        self.assertPathExists(tmpfile)
        os.remove(tmpfile)


class TestCheckAvailability(tests.TestCaseInTempDir):

    def test_full_path(self):
        self.assertTrue(mergetools.check_availability(sys.executable))

    def test_nonexistent(self):
        self.assertFalse(mergetools.check_availability('DOES NOT EXIST'))

    def test_non_executable(self):
        f, name = tempfile.mkstemp()
        try:
            self.log('temp filename: %s', name)
            self.assertFalse(mergetools.check_availability(name))
        finally:
            os.close(f)
            os.unlink(name)


class TestInvoke(tests.TestCaseInTempDir):
    def setUp(self):
        super(tests.TestCaseInTempDir, self).setUp()
        self._exe = None
        self._args = None
        self.build_tree_contents((
            ('test.txt', b'stuff'),
            ('test.txt.BASE', b'base stuff'),
            ('test.txt.THIS', b'this stuff'),
            ('test.txt.OTHER', b'other stuff'),
        ))

    def test_invoke_expands_exe_path(self):
        self.overrideEnv('PATH', os.path.dirname(sys.executable))

        def dummy_invoker(exe, args, cleanup):
            self._exe = exe
            self._args = args
            cleanup(0)
            return 0
        command = '%s {result}' % os.path.basename(sys.executable)
        retcode = mergetools.invoke(command, 'test.txt', dummy_invoker)
        self.assertEqual(0, retcode)
        self.assertEqual(sys.executable, self._exe)
        self.assertEqual(['test.txt'], self._args)

    def test_success(self):
        def dummy_invoker(exe, args, cleanup):
            self._exe = exe
            self._args = args
            cleanup(0)
            return 0
        retcode = mergetools.invoke('tool {result}', 'test.txt', dummy_invoker)
        self.assertEqual(0, retcode)
        self.assertEqual('tool', self._exe)
        self.assertEqual(['test.txt'], self._args)

    def test_failure(self):
        def dummy_invoker(exe, args, cleanup):
            self._exe = exe
            self._args = args
            cleanup(1)
            return 1
        retcode = mergetools.invoke('tool {result}', 'test.txt', dummy_invoker)
        self.assertEqual(1, retcode)
        self.assertEqual('tool', self._exe)
        self.assertEqual(['test.txt'], self._args)

    def test_success_tempfile(self):
        def dummy_invoker(exe, args, cleanup):
            self._exe = exe
            self._args = args
            self.assertPathExists(args[0])
            with open(args[0], 'wt') as f:
                f.write('temp stuff')
            cleanup(0)
            return 0
        retcode = mergetools.invoke('tool {this_temp}', 'test.txt',
                                    dummy_invoker)
        self.assertEqual(0, retcode)
        self.assertEqual('tool', self._exe)
        self.assertPathDoesNotExist(self._args[0])
        self.assertFileEqual(b'temp stuff', 'test.txt')

    def test_failure_tempfile(self):
        def dummy_invoker(exe, args, cleanup):
            self._exe = exe
            self._args = args
            self.assertPathExists(args[0])
            self.log(repr(args))
            with open(args[0], 'wt') as f:
                self.log(repr(f))
                f.write('temp stuff')
            cleanup(1)
            return 1
        retcode = mergetools.invoke('tool {this_temp}', 'test.txt',
                                    dummy_invoker)
        self.assertEqual(1, retcode)
        self.assertEqual('tool', self._exe)
        self.assertFileEqual(b'stuff', 'test.txt')
