# Copyright (C) 2005 Canonical Ltd
# -*- coding: utf-8 -*-
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


"""Black-box tests for bzr.

These check that it behaves properly when it's invoked through the regular
command-line interface. This doesn't actually run a new interpreter but 
rather starts again from the run_bzr function.
"""


from cStringIO import StringIO
import os
import shutil
import sys

from bzrlib.branch import Branch
from bzrlib.errors import BzrCommandError
from bzrlib.osutils import has_symlinks
from bzrlib.tests import TestCaseWithTransport
from bzrlib.annotate import annotate_file


class TestAnnotate(TestCaseWithTransport):

    def setUp(self):
        super(TestAnnotate, self).setUp()
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree_contents([('hello.txt', 'my helicopter\n'),
                                  ('nomail.txt', 'nomail\n')])
        wt.add(['hello.txt'])
        self.rev_id_1 = wt.commit('add hello', committer='test@user')
        wt.add(['nomail.txt'])
        self.rev_id_2 = wt.commit('add nomail', committer='no mail')
        file('hello.txt', 'ab').write('your helicopter')
        self.rev_id_3 = wt.commit('mod hello', committer='user@test')

    def test_help_annotate(self):
        """Annotate command exists"""
        out, err = self.run_bzr('--no-plugins', 'annotate', '--help')

    def test_annotate_cmd(self):
        out, err = self.run_bzr('annotate', 'hello.txt')
        self.assertEqual('', err)
        self.assertEqualDiff('''\
1   test@us | my helicopter
3   user@te | your helicopter
''', out)

    def test_no_mail(self):
        out, err = self.run_bzr('annotate', 'nomail.txt')
        self.assertEqual('', err)
        self.assertEqualDiff('''\
2   no mail | nomail
''', out)

    def test_annotate_cmd_revision(self):
        out, err = self.run_bzr('annotate', 'hello.txt', '-r1')
        self.assertEqual('', err)
        self.assertEqualDiff('''\
1   test@us | my helicopter
''', out)

    def test_annotate_cmd_revision3(self):
        out, err = self.run_bzr('annotate', 'hello.txt', '-r3')
        self.assertEqual('', err)
        self.assertEqualDiff('''\
1   test@us | my helicopter
3   user@te | your helicopter
''', out)

    def test_annotate_cmd_unknown_revision(self):
        out, err = self.run_bzr('annotate', 'hello.txt', '-r', '10',
                                retcode=3)
        self.assertEqual('', out)
        self.assertContainsRe(err, 'Requested revision: \'10\' does not exist')

    def test_annotate_cmd_two_revisions(self):
        out, err = self.run_bzr('annotate', 'hello.txt', '-r1..2',
                                retcode=3)
        self.assertEqual('', out)
        self.assertEqual('bzr: ERROR: bzr annotate --revision takes'
                         ' exactly 1 argument\n',
                         err)

    def test_annotate_empty_file(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/empty', '')])
        tree.add('empty')
        tree.commit('add empty file')

        os.chdir('tree')
        out, err = self.run_bzr('annotate', 'empty')
        self.assertEqual('', out)
