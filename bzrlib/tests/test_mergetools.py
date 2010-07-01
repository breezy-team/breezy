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

from bzrlib import (
    config,
    mergetools,
    tests
)


class TestMergeTool(tests.TestCaseInTempDir):
    def test_get_name(self):
        mt = mergetools.MergeTool('kdiff3 %b %t %o -o %r')
        self.assertEquals('kdiff3', mt.get_name())
        mt = mergetools.MergeTool('/foo/bar/kdiff3 %b %t %o -o %r')
        self.assertEquals('kdiff3', mt.get_name())
        mt = mergetools.MergeTool('"C:\\Program Files\\KDiff3\\kdiff3.exe" %b %t %o -o %r')
        self.assertEquals('kdiff3.exe', mt.get_name())

    def test_expand_commandline(self):
        mt = mergetools.MergeTool('kdiff3 %b %t %o -o %r')
        commandline, _ = mt._expand_commandline('test.txt')
        self.assertEquals(
            'kdiff3 test.txt.BASE test.txt.THIS test.txt.OTHER -o test.txt',
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
