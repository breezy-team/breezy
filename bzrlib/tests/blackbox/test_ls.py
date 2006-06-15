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
#

"""Tests of the 'bzr ls' command."""


import os

from bzrlib.bzrdir import BzrDir 
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestCommands(ExternalBase):

    def test_ls(self):
        """Test the abilities of 'bzr ls'"""
        bzr = self.runbzr
        def bzrout(*args, **kwargs):
            kwargs['backtick'] = True
            return self.runbzr(*args, **kwargs)

        def ls_equals(value, *args):
            out = self.runbzr(['ls'] + list(args), backtick=True)
            self.assertEquals(out, value)

        bzr('init')
        open('a', 'wb').write('hello\n')

        # Can't supply both
        bzr('ls --verbose --null', retcode=3)

        ls_equals('a\n')
        ls_equals('?        a\n', '--verbose')
        ls_equals('a\n', '--unknown')
        ls_equals('', '--ignored')
        ls_equals('', '--versioned')
        ls_equals('a\n', '--unknown', '--ignored', '--versioned')
        ls_equals('', '--ignored', '--versioned')
        ls_equals('a\0', '--null')

        bzr('add a')
        ls_equals('V        a\n', '--verbose')
        bzr('commit -m add')
        
        os.mkdir('subdir')
        ls_equals('V        a\n'
                  '?        subdir/\n'
                  , '--verbose')
        open('subdir/b', 'wb').write('b\n')
        bzr('add')
        ls_equals('V        a\n'
                  'V        subdir/\n'
                  'V        subdir/b\n'
                  , '--verbose')
        bzr('commit -m subdir')

        ls_equals('a\n'
                  'subdir\n'
                  , '--non-recursive')

        ls_equals('V        a\n'
                  'V        subdir/\n'
                  , '--verbose', '--non-recursive')

        # Check what happens in a sub-directory
        os.chdir('subdir')
        ls_equals('b\n')
        ls_equals('b\0'
                  , '--null')
        ls_equals('a\n'
                  'subdir\n'
                  'subdir/b\n'
                  , '--from-root')
        ls_equals('a\0'
                  'subdir\0'
                  'subdir/b\0'
                  , '--from-root', '--null')
        ls_equals('a\n'
                  'subdir\n'
                  , '--from-root', '--non-recursive')

        os.chdir('..')

        # Check what happens when we supply a specific revision
        ls_equals('a\n', '--revision', '1')
        ls_equals('V        a\n'
                  , '--verbose', '--revision', '1')

        os.chdir('subdir')
        ls_equals('', '--revision', '1')

        # Now try to do ignored files.
        os.chdir('..')
        open('blah.py', 'wb').write('unknown\n')
        open('blah.pyo', 'wb').write('ignored\n')
        ls_equals('a\n'
                  'blah.py\n'
                  'blah.pyo\n'
                  'subdir\n'
                  'subdir/b\n')
        ls_equals('V        a\n'
                  '?        blah.py\n'
                  'I        blah.pyo\n'
                  'V        subdir/\n'
                  'V        subdir/b\n'
                  , '--verbose')
        ls_equals('blah.pyo\n'
                  , '--ignored')
        ls_equals('blah.py\n'
                  , '--unknown')
        ls_equals('a\n'
                  'subdir\n'
                  'subdir/b\n'
                  , '--versioned')

    def test_ls_debris(self):
        self.build_tree(['file',
                         'file~',
                         'file.BASE',
                         'file.THIS',
                         'file.OTHER',
                         'test1234.tmp',
                         'file.pyc'])
        BzrDir.create_standalone_workingtree('.')
        output = self.runbzr('ls --debris', backtick=True)
        self.assertEqualDiff(output, 
                             'file.BASE\n'
                             'file.OTHER\n'
                             'file.THIS\n'
                             'file~\n'
                             'test1234.tmp\n')
        wt = WorkingTree.open('.')
        wt.add(['file.BASE', 'file~', 'test1234.tmp'])
        output = self.runbzr('ls --debris', backtick=True)
        self.assertEqualDiff(output, 'file.OTHER\n' 'file.THIS\n')
