# Copyright (C) 2006 by Canonical Ltd
# -*- coding: utf-8 -*-

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

import os

from bzrlib.tests.blackbox import ExternalBase

class TestConflicts(ExternalBase):
    def setUp(self):
        super(ExternalBase, self).setUp()
        try:
            os.mkdir('a')
        except:
            raise os.getcwd()
        os.chdir('a')
        self.runbzr('init')
        file('myfile', 'wb').write('contentsa\n')
        file('my_other_file', 'wb').write('contentsa\n')
        self.runbzr('add')
        self.runbzr('commit -m new')
        os.chdir('..')
        self.runbzr('branch a b')
        os.chdir('b')
        file('myfile', 'wb').write('contentsb\n')
        file('my_other_file', 'wb').write('contentsb\n')
        self.runbzr('commit -m change')
        os.chdir('../a')
        file('myfile', 'wb').write('contentsa2\n')
        file('my_other_file', 'wb').write('contentsa2\n')
        self.runbzr('commit -m change')
        self.runbzr('merge ../b', retcode=1)

    def test_conflicts(self):
        conflicts = self.runbzr('conflicts', backtick=True)
        self.assertEqual(len(conflicts.splitlines()), 2)

    def test_resolve(self):
        self.runbzr('resolve', retcode=3)
        self.runbzr('resolve myfile')
        conflicts = self.runbzr('conflicts', backtick=True)
        self.assertEqual(len(conflicts.splitlines()), 1)
        self.runbzr('resolve my_other_file')
        conflicts = self.runbzr('conflicts', backtick=True)
        self.assertEqual(len(conflicts.splitlines()), 0)

    def test_resolve_all(self):
        self.runbzr('resolve --all')
        conflicts = self.runbzr('conflicts', backtick=True)
        self.assertEqual(len(conflicts.splitlines()), 0)

