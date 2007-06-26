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
from bzrlib.tests.blackbox import ExternalBase
import os


class TestFindMergeBase(ExternalBase):

    def test_find_merge_base(self):
        os.mkdir('a')
        os.chdir('a')
        self.run_bzr('init')
        self.run_bzr('commit -m foo --unchanged')
        self.run_bzr('branch . ../b')
        q = self.run_bzr(['find-merge-base', '.', '../b'])[0]
        self.run_bzr('commit -m bar --unchanged')
        os.chdir('../b')
        self.run_bzr('commit -m baz --unchanged')
        r = self.run_bzr(['find-merge-base', '.', '../a'])[0]
        self.assertEqual(q, r)
        
