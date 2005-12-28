# Copyright (C) 2005 Canonical Ltd

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

"""\
Tests for version_info
"""

import os

from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.branch import Branch

# TODO: jam 20051228 When part of bzrlib, this should become
#       from bzrlib.generate_version_info import foo

from generate_version_info import is_clean
from errors import UncleanError


class TestIsClean(TestCaseInTempDir):

    # TODO: jam 20051228 Test that a branch without a working tree
    #       is clean. This would be something like an SFTP test

    def test_is_clean(self):
        b = Branch.initialize('.')
        wt = b.working_tree()

        def not_clean(b):
            clean, message = is_clean(b)
            if clean:
                self.fail('Tree should not be clean')

        def check_clean(b):
            clean, message = is_clean(b)
            if not clean:
                self.fail(message)

        # Nothing happened yet
        check_clean(b)

        # Unknown file
        open('a', 'wb').write('a file\n')
        not_clean(b)
        
        # Newly added file
        wt.add('a')
        not_clean(b)

        # We committed, things are clean
        wt.commit('added a')
        check_clean(b)

        # Unknown
        open('b', 'wb').write('b file\n')
        not_clean(b)

        wt.add('b')
        not_clean(b)

        wt.commit('added b')
        check_clean(b)

        open('a', 'wb').write('different\n')
        not_clean(b)

        wt.commit('mod a')
        check_clean(b)

        os.remove('a')
        not_clean(b)

        wt.commit('del a')
        check_clean(b)

        wt.rename_one('b', 'a')
        not_clean(b)

        wt.commit('rename b => a')
        check_clean(b)


class TestVersionInfo(TestCaseInTempDir):
    pass

