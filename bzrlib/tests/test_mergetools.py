# Copyright (C) 2005-2010 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
#            and others
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


class TestMergeTool(tests.TestCaseInTempDir):
    def test_basics(self):
        mt = mergetools.MergeTool('/path/to/tool --opt %b -x %t %o --stuff %r')
        self.assertEquals('/path/to/tool --opt %b -x %t %o --stuff %r', mt.get_commandline())
        self.assertEquals('/path/to/tool', mt.get_executable())
        self.assertEquals('--opt %b -x %t %o --stuff %r', mt.get_arguments())
        self.assertEquals('tool', mt.get_name())
        mt.set_commandline('/new/path/to/bettertool %b %t %o %r')
        self.assertEquals('/new/path/to/bettertool %b %t %o %r', mt.get_commandline())
        self.assertEquals('/new/path/to/bettertool', mt.get_executable())
        self.assertEquals('%b %t %o %r', mt.get_arguments())
        mt.set_executable('othertool')
        self.assertEquals('othertool', mt.get_executable())
        self.assertEquals('othertool %b %t %o %r', mt.get_commandline())
        mt.set_arguments('%r %b %t %o')
        self.assertEquals('%r %b %t %o', mt.get_arguments())
        self.assertEquals('othertool %r %b %t %o', mt.get_commandline())
        
    def test_quoted_executable(self):
        mt = mergetools.MergeTool('"C:\\Program Files\\KDiff3\\kdiff3.exe" %b %t %o -o %r')
        self.assertEquals('kdiff3.exe', mt.get_name())

    def test_expand_commandline(self):
        mt = mergetools.MergeTool('kdiff3 %b %t %o -o %r')
        commandline, _ = mt._expand_commandline('test.txt')
        self.assertEquals(
            'kdiff3 test.txt.BASE test.txt.THIS test.txt.OTHER -o test.txt',
            commandline)
        commandline, _ = mt._expand_commandline('file with space.txt')
        self.assertEquals(
            'kdiff3 "file with space.txt.BASE" "file with space.txt.THIS" "file with space.txt.OTHER" -o "file with space.txt"',
            commandline)
        commandline, _ = mt._expand_commandline('file with "space and quotes".txt')
        self.assertEquals(
            'kdiff3 "file with \\"space and quotes\\".txt.BASE" "file with \\"space and quotes\\".txt.THIS" "file with \\"space and quotes\\".txt.OTHER" -o "file with \\"space and quotes\\".txt"',
            commandline)
        
    def test_expand_commandline_tempfile(self):
        self.build_tree(('test.txt', 'test.txt.BASE', 'test.txt.THIS',
                         'test.txt.OTHER'))
        mt = mergetools.MergeTool('some_tool %T')
        commandline, tmpfile = mt._expand_commandline('test.txt')
        self.assertStartsWith(commandline, 'some_tool ')
        m = re.match('some_tool (.*)', commandline)
        self.assertEquals(tmpfile, m.group(1))
        self.failUnlessExists(m.group(1))
        os.remove(tmpfile)
        
    def test_is_available(self):
        mt = mergetools.MergeTool('%s' % sys.executable)
        self.assertTrue(mt.is_available())
        mt.set_executable(os.path.basename(sys.executable))
        self.assertTrue(mt.is_available())
        mt.set_executable("ThisExecutableShouldReallyNotExist")
        self.assertFalse(mt.is_available())
