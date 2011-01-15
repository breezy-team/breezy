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
import re
import sys
import tempfile

from bzrlib import (
    config,
    mergetools,
    tests
)
from bzrlib.tests.features import backslashdir_feature


class TestBasics(tests.TestCase):

    def setUp(self):
        super(TestBasics, self).setUp()
        self.tool = mergetools.MergeTool('sometool',
            '/path/to/tool --opt {base} -x {this} {other} --stuff {result}')

    def test_get_commandline(self):
        self.assertEqual(
            '/path/to/tool --opt {base} -x {this} {other} --stuff {result}',
            self.tool.command_line)
        
    def test_set_commandline(self):
        self.tool.command_line = "/path/to/tool blah"
        self.assertEqual("/path/to/tool blah", self.tool.command_line)
        self.assertEqual(['/path/to/tool', 'blah'], self.tool._cmd_list)

    def test_get_name(self):
        self.assertEqual('sometool', self.tool.name)


class TestUnicodeBasics(tests.TestCase):

    def setUp(self):
        super(TestUnicodeBasics, self).setUp()
        self.tool = mergetools.MergeTool(
            u'someb\u0414r',
            u'/path/to/b\u0414r --opt {base} -x {this} {other}'
            ' --stuff {result}')

    def test_get_commandline(self):
        self.assertEqual(
            u'/path/to/b\u0414r --opt {base} -x {this} {other}'
            ' --stuff {result}',
            self.tool.command_line)

    def test_get_name(self):
        self.assertEqual(u'someb\u0414r', self.tool.name)


class TestMergeToolOperations(tests.TestCaseInTempDir):

    def test_filename_substitution(self):
        def dummy_invoker(executable, args, cleanup):
            self._commandline = [executable] + args
            cleanup(0)
        mt = mergetools.MergeTool('kdiff3',
                                  'kdiff3 {base} {this} {other} -o {result}')
        mt.invoke('test.txt', dummy_invoker)
        self.assertEqual(
            ['kdiff3',
             'test.txt.BASE',
             'test.txt.THIS',
             'test.txt.OTHER',
             '-o',
             'test.txt'],
            self._commandline)
        mt.invoke('file with space.txt', dummy_invoker)
        self.assertEqual(
            ['kdiff3',
             "file with space.txt.BASE",
             "file with space.txt.THIS",
             "file with space.txt.OTHER",
             '-o',
             "file with space.txt"],
            self._commandline)
        mt.invoke('file with "space and quotes".txt', dummy_invoker)
        self.assertEqual(
            ['kdiff3',
             "file with \"space and quotes\".txt.BASE",
             "file with \"space and quotes\".txt.THIS",
             "file with \"space and quotes\".txt.OTHER",
             '-o',
             "file with \"space and quotes\".txt"],
            self._commandline)

    def test_expand_commandline_tempfile(self):
        def dummy_invoker(executable, args, cleanup):
            self.assertEqual('some_tool', executable)
            self.failUnlessExists(args[0])
            cleanup(0)
            self._tmp_file = args[0]
        self.build_tree(('test.txt', 'test.txt.BASE', 'test.txt.THIS',
                         'test.txt.OTHER'))
        mt = mergetools.MergeTool('some_tool', 'some_tool {this_temp}')
        mt.invoke('test.txt', dummy_invoker)
        self.failIfExists(self._tmp_file)

    def test_is_available_full_tool_path(self):
        mt = mergetools.MergeTool(None, sys.executable)
        self.assertTrue(mt.is_available())

    def test_is_available_tool_on_path(self):
        mt = mergetools.MergeTool(None, os.path.basename(sys.executable))
        self.assertTrue(mt.is_available())

    def test_is_available_nonexistent(self):
        mt = mergetools.MergeTool(None, "ThisExecutableShouldReallyNotExist")
        self.assertFalse(mt.is_available())

    def test_is_available_non_executable(self):
        f, name = tempfile.mkstemp()
        try:
            self.log('temp filename: %s', name)
            mt = mergetools.MergeTool('temp', name)
            self.assertFalse(mt.is_available())
        finally:
            os.close(f)
            os.unlink(name)
