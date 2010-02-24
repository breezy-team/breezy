# Copyright (C) 2010 Canonical Ltd
# Copyright (C) 2010 Parth Malwankar <parth.malwankar@gmail.com>
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

import os
import re

from bzrlib import tests

class TestGrep(tests.TestCaseWithTransport):
    def _str_contains(self, base, pattern):
        return re.search(pattern, base) != None

    def test_basic_unversioned_file_grep(self):
        """search for pattern in specfic file"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        open('file0.txt', 'w').write('line1\nline2\nline3')
        out, err = self.run_bzr(['grep', 'line1', 'file0.txt'])
        self.assertTrue(out, self._str_contains(out, "file0.txt:1:line1"))
        self.assertTrue(err, self._str_contains(err, "warning:.*file0.txt.*not versioned\."))

