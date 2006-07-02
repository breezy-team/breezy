# Copyright (C) 2005, 2006 by Canonical Ltd
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

from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestRemerge(ExternalBase):

    def make_file(self, name, contents):
        f = open(name, 'wb')
        try:
            f.write(contents)
        finally:
            f.close()

    def create_conflicts(self):
        """Create a conflicted tree"""
        os.mkdir('base')
        os.chdir('base')
        self.make_file('hello', "hi world")
        self.make_file('answer', "42")
        self.run_bzr('init')
        self.run_bzr('add')
        self.run_bzr('commit', '-m', 'base')
        self.run_bzr('branch', '.', '../other')
        self.run_bzr('branch', '.', '../this')
        os.chdir('../other')
        self.make_file('hello', "Hello.")
        self.make_file('answer', "Is anyone there?")
        self.run_bzr('commit', '-m', 'other')
        os.chdir('../this')
        self.make_file('hello', "Hello, world")
        self.run_bzr('mv', 'answer', 'question')
        self.make_file('question', "What do you get when you multiply six"
                                   "times nine?")
        self.run_bzr('commit', '-m', 'this')

    def test_remerge(self):
        """Remerge command works as expected"""
        self.create_conflicts()
        self.run_bzr('merge', '../other', '--show-base', retcode=1)
        conflict_text = open('hello').read()
        self.assertTrue('|||||||' in conflict_text)
        self.assertTrue('hi world' in conflict_text)

        self.run_bzr_error(['conflicts encountered'], 'remerge', retcode=1)
        conflict_text = open('hello').read()
        self.assertFalse('|||||||' in conflict_text)
        self.assertFalse('hi world' in conflict_text)

        os.unlink('hello.OTHER')
        os.unlink('question.OTHER')

        self.run_bzr_error(['jello is not versioned'],
                     'remerge', 'jello', '--merge-type', 'weave')
        self.run_bzr_error(['conflicts encountered'],
                           'remerge', 'hello', '--merge-type', 'weave',
                           retcode=1)

        self.failUnlessExists('hello.OTHER')
        self.failIfExists('question.OTHER')

        file_id = self.run_bzr('file-id', 'hello')[0]
        self.run_bzr_error(['\'hello.THIS\' is not a versioned file'],
                           'file-id', 'hello.THIS')

        self.run_bzr_error(['conflicts encountered'],
                           'remerge', '--merge-type', 'weave', retcode=1)

        self.failUnlessExists('hello.OTHER')
        self.failIfExists('hello.BASE')
        self.assertFalse('|||||||' in conflict_text)
        self.assertFalse('hi world' in conflict_text)

        self.run_bzr_error(['Showing base is not supported.*Weave'],
                           'remerge', '.', '--merge-type', 'weave', '--show-base')
        self.run_bzr_error(['Can\'t reprocess and show base'],
                           'remerge', '.', '--show-base', '--reprocess')
        self.run_bzr_error(['conflicts encountered'],
                           'remerge', '.', '--merge-type', 'weave', '--reprocess',
                           retcode=1)
        self.run_bzr_error(['conflicts encountered'],
                           'remerge', 'hello', '--show-base',
                           retcode=1)
        self.run_bzr_error(['conflicts encountered'],
                           'remerge', 'hello', '--reprocess', retcode=1)

        self.run_bzr('resolve', '--all')
        self.run_bzr('commit', '-m', 'done')

        self.run_bzr_error(['remerge only works after normal merges',
                            'Not cherrypicking or multi-merges'],
                           'remerge')

    def test_conflicts(self):
        self.create_conflicts()
        self.run_bzr('merge', '../other', retcode=1)
        wt = WorkingTree.open('.')
        self.assertEqual(len(wt.conflicts()), 2)
        self.run_bzr('remerge', retcode=1)
        wt = WorkingTree.open('.')
        self.assertEqual(len(wt.conflicts()), 2)
        self.run_bzr('remerge', 'hello', retcode=1)
        self.assertEqual(len(wt.conflicts()), 2)
