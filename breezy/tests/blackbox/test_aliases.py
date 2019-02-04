# Copyright (C) 2006, 2007, 2009, 2010, 2016 Canonical Ltd
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
"""Black-box tests for brz aliases.
"""

import os

from breezy import config
from breezy.branch import Branch
from breezy.tests import TestCaseWithTransport
from breezy.trace import mutter


class TestAliases(TestCaseWithTransport):

    def test_aliases(self):

        def bzr(args, **kwargs):
            return self.run_bzr(args, **kwargs)[0]

        def bzr_catch_error(args, **kwargs):
            return self.run_bzr(args, **kwargs)[1]

        conf = config.GlobalConfig.from_string(b'''[ALIASES]
c=cat
c1=cat -r 1
c2=cat -r 1 -r2
''', save=True)

        str1 = 'foo\n'
        str2 = 'bar\n'

        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('a', str1)])
        tree.add('a')
        tree.commit(message='1')

        self.assertEqual(bzr('c a'), str1)

        self.build_tree_contents([('a', str2)])
        tree.commit(message='2')

        self.assertEqual(bzr('c a'), str2)
        self.assertEqual(bzr('c1 a'), str1)
        self.assertEqual(bzr('c1 --revision 2 a'), str2)

        # If --no-aliases isn't working, we will not get retcode=3
        bzr('--no-aliases c a', retcode=3)

        # If --no-aliases breaks all of bzr, we also get retcode=3
        # So we need to catch the output as well
        self.assertEqual(bzr_catch_error('--no-aliases c a',
                                         retcode=None),
                         'brz: ERROR: unknown command "c". '
                         'Perhaps you meant "ci"\n')

        bzr('c -r1 -r2', retcode=3)
        bzr('c1 -r1 -r2', retcode=3)
        bzr('c2', retcode=3)
        bzr('c2 -r1', retcode=3)
