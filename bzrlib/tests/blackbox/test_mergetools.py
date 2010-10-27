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

from bzrlib import (
    mergetools,
    tests
)

class TestMergeTools(tests.TestCaseInTempDir):
    def test_add(self):
        self.run_bzr('mergetools --add meld %b %T %o')
        tools = mergetools.get_merge_tools()
        self.assertEquals(['meld %b %T %o'],
            [mt.get_commandline() for mt in tools])
        
    def test_update(self):
        self.run_bzr('mergetools --add meld %b %T %o')
        self.run_bzr('mergetools --update=meld meld %b stuff %T %o')
        tools = mergetools.get_merge_tools()
        self.assertEquals(['meld %b stuff %T %o'],
            [mt.get_commandline() for mt in tools])
        
    def test_list(self):
        self.run_bzr('mergetools --add meld %b %T %o')
        out, err = self.run_bzr('mergetools --list')
        self.assertContainsRe(out, 'meld %b %T %o')
        
    def test_remove(self):
        self.run_bzr('mergetools --add meld %b %T %o')
        self.run_bzr('mergetools --remove meld')
        self.assertLength(0, mergetools.get_merge_tools())
