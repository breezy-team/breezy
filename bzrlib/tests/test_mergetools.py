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
            self.tool.get_commandline())

    def test_get_commandline_as_list(self):
        self.assertEqual(
            ['/path/to/tool', '--opt', '{base}', '-x', '{this}', '{other}',
             '--stuff', '{result}'],
            self.tool.get_commandline_as_list())

    def test_get_executable(self):
        self.assertEqual('/path/to/tool', self.tool.get_executable())

    def test_get_name(self):
        self.assertEqual('sometool', self.tool.get_name())

    def test_set_name(self):
        self.tool.set_name('bettertool')
        self.assertEqual('bettertool', self.tool.get_name())

    def test_set_name_none(self):
        self.tool.set_name(None)
        self.assertEqual('tool', self.tool.get_name())

    def test_set_commandline(self):
        self.tool.set_commandline(
            '/new/path/to/bettertool {base} {this} {other} {result}')
        self.assertEqual(
            ['/new/path/to/bettertool', '{base}', '{this}', '{other}',
             '{result}'],
            self.tool.get_commandline_as_list())

    def test_set_executable(self):
        self.tool.set_executable('othertool')
        self.assertEqual(
            ['othertool', '--opt', '{base}', '-x', '{this}', '{other}',
             '--stuff', '{result}'],
            self.tool.get_commandline_as_list())

    def test_quoted_executable(self):
        self.requireFeature(backslashdir_feature)
        self.tool.set_commandline('"C:\\Program Files\\KDiff3\\kdiff3.exe" '
                                  '{base} {this} {other} -o {result}')
        self.assertEqual('C:\\Program Files\\KDiff3\\kdiff3.exe',
                         self.tool.get_executable())

    def test_comparison(self):
        other_tool = mergetools.MergeTool('sometool',
            '/path/to/tool --opt {base} -x {this} {other} --stuff {result}')
        self.assertTrue(self.tool == other_tool)
        self.assertTrue(self.tool != None)

    def test_comparison_none(self):
        self.assertFalse(self.tool == None)
        self.assertTrue(self.tool != None)

    def test_comparison_fail_name(self):
        other_tool = mergetools.MergeTool('sometoolx',
            '/path/to/tool --opt {base} -x {this} {other} --stuff {result}')
        self.assertFalse(self.tool == other_tool)
        self.assertTrue(self.tool != other_tool)

    def test_comparison_fail_commandline(self):
        other_tool = mergetools.MergeTool('sometool',
            '/path/to/tool --opt {base} -x {other} --stuff {result} extra')
        self.assertFalse(self.tool == other_tool)
        self.assertTrue(self.tool != other_tool)


class TestUnicodeBasics(tests.TestCase):
    def setUp(self):
        super(TestUnicodeBasics, self).setUp()
        self.tool = mergetools.MergeTool(u'someb\u0414r',
            u'/path/to/b\u0414r --opt {base} -x {this} {other} --stuff {result}')

    def test_get_commandline(self):
        self.assertEqual(
            u'/path/to/b\u0414r --opt {base} -x {this} {other} --stuff {result}',
            self.tool.get_commandline())

    def test_get_commandline_as_list(self):
        self.assertEqual(
            [u'/path/to/b\u0414r', u'--opt', u'{base}', u'-x', u'{this}',
             u'{other}', u'--stuff', u'{result}'],
            self.tool.get_commandline_as_list())

    def test_get_executable(self):
        self.assertEqual(u'/path/to/b\u0414r', self.tool.get_executable())

    def test_get_name(self):
        self.assertEqual(u'someb\u0414r', self.tool.get_name())

    def test_set_name(self):
        self.tool.set_name(u'betterb\u0414r')
        self.assertEqual(u'betterb\u0414r', self.tool.get_name())

    def test_set_name_none(self):
        self.tool.set_name(None)
        self.assertEqual(u'b\u0414r', self.tool.get_name())

    def test_set_commandline(self):
        self.tool.set_commandline(
            u'/new/path/to/betterb\u0414r {base} {this} {other} {result}')
        self.assertEqual(
            [u'/new/path/to/betterb\u0414r', u'{base}', u'{this}', u'{other}',
             u'{result}'],
            self.tool.get_commandline_as_list())

    def test_set_executable(self):
        self.tool.set_executable(u'otherb\u0414r')
        self.assertEqual(
            [u'otherb\u0414r', u'--opt', u'{base}', u'-x', u'{this}',
             u'{other}', u'--stuff', u'{result}'],
            self.tool.get_commandline_as_list())

    def test_quoted_executable(self):
        self.requireFeature(backslashdir_feature)
        self.tool.set_commandline(u'"C:\\Program Files\\KDiff3\\b\u0414r.exe" '
                                  '{base} {this} {other} -o {result}')
        self.assertEqual(u'C:\\Program Files\\KDiff3\\b\u0414r.exe',
                         self.tool.get_executable())

    def test_comparison(self):
        other_tool = mergetools.MergeTool(u'someb\u0414r',
            u'/path/to/b\u0414r --opt {base} -x {this} {other} --stuff {result}')
        self.assertTrue(self.tool == other_tool)
        self.assertFalse(self.tool != other_tool)

    def test_comparison_none(self):
        self.assertFalse(self.tool == None)
        self.assertTrue(self.tool != None)

    def test_comparison_fail_name(self):
        other_tool = mergetools.MergeTool(u'someb\u0414rx',
            u'/path/to/b\u0414r --opt {base} -x {this} {other} --stuff {result}')
        self.assertFalse(self.tool == other_tool)
        self.assertTrue(self.tool != other_tool)

    def test_comparison_fail_commandline(self):
        other_tool = mergetools.MergeTool(u'someb\u0414r',
            u'/path/to/b\u0414r --opt {base} -x {other} --stuff {result} extra')
        self.assertFalse(self.tool == other_tool)
        self.assertTrue(self.tool != other_tool)


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

    def test_empty_commandline(self):
        mt = mergetools.MergeTool('', '')
        self.assertEqual('', mt.get_commandline())

    def test_no_arguments(self):
        mt = mergetools.MergeTool('tool', 'tool')
        self.assertEqual('tool', mt.get_commandline())


class TestModuleFunctions(tests.TestCaseInTempDir):
    def test_detect(self):
        # only way to reliably test detection is to add a known existing
        # executable to the list used for detection
        old_kmt = mergetools._KNOWN_MERGE_TOOLS
        mergetools._KNOWN_MERGE_TOOLS = ['sh', 'cmd']
        tools = mergetools.detect_merge_tools()
        tools_commandlines = [mt.get_commandline() for mt in tools]
        self.assertTrue('sh' in tools_commandlines or
                        'cmd' in tools_commandlines)
        mergetools._KNOWN_MERGE_TOOLS = old_kmt
