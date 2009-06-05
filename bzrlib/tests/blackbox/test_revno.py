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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""Black-box tests for bzr revno.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseWithTransport

class TestRevno(TestCaseWithTransport):

    def test_revno(self):

        def bzr(*args, **kwargs):
            return self.run_bzr(*args, **kwargs)[0]

        os.mkdir('a')
        os.chdir('a')
        bzr('init')
        self.assertEquals(int(bzr('revno')), 0)

        open('foo', 'wb').write('foo\n')
        bzr('add foo')
        bzr('commit -m foo')
        self.assertEquals(int(bzr('revno')), 1)

        os.mkdir('baz')
        bzr('add baz')
        bzr('commit -m baz')
        self.assertEquals(int(bzr('revno')), 2)

        os.chdir('..')
        self.assertEquals(int(bzr('revno a')), 2)
        self.assertEquals(int(bzr('revno a/baz')), 2)

    def test_revno_tree(self):
        # Make branch and checkout
        wt = self.make_branch_and_tree('branch')
        checkout = wt.branch.create_checkout('checkout', lightweight=True)

        # Get the checkout out of date
        self.build_tree(['branch/file'])
        wt.add(['file'])
        wt.commit('mkfile')

        # Make sure revno says we're on 1
        out,err = self.run_bzr('revno checkout')
        self.assertEqual('', err)
        self.assertEqual('1\n', out)

        # Make sure --tree knows it's still on 0
        out,err = self.run_bzr('revno --tree checkout')
        self.assertEqual('', err)
        self.assertEqual('0\n', out)

    def test_dotted_revno_tree(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'content\n'))])
        builder.build_snapshot('B-id', ['A-id'], [])
        builder.build_snapshot('C-id', ['A-id', 'B-id'], [])
        builder.finish_series()
        b = builder.get_branch()
        co_b = b.create_checkout('checkout_b', lightweight=True,
                                 revision_id='B-id')
        out, err = self.run_bzr('revno checkout_b')
        self.assertEqual('', err)
        self.assertEqual('2\n', out)
        out, err = self.run_bzr('revno --tree checkout_b')
        self.assertEqual('', err)
        self.assertEqual('1.1.1\n', out)

    def test_stale_revno_tree(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'content\n'))])
        builder.build_snapshot('B-id', ['A-id'], [])
        builder.build_snapshot('C-id', ['A-id'], [])
        builder.finish_series()
        b = builder.get_branch()
        # The branch is now at "C-id", but the checkout is still at "B-id"
        # which is no longer in the history
        co_b = b.create_checkout('checkout_b', lightweight=True,
                                 revision_id='B-id')
        out, err = self.run_bzr('revno checkout_b')
        self.assertEqual('', err)
        self.assertEqual('2\n', out)
        out, err = self.run_bzr('revno --tree checkout_b')
        self.assertEqual('', err)
        self.assertEqual('???\n', out)
