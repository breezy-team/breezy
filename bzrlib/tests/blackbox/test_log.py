# Copyright (C) 2005 by Canonical Ltd
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


"""Black-box tests for bzr log.
"""

import os

import bzrlib
from bzrlib.tests.blackbox import ExternalBase


class TestLog(ExternalBase):

    def test_log(self):
        self.runbzr("init")
        self.build_tree(['hello.txt'])
        self.runbzr("add hello.txt")
        self.runbzr("commit -m message hello.txt")
        result = self.runbzr("log")[0]
        self.assertTrue('revno: 1\n' in result)
        self.assertTrue('message:\n  message\n' in result)
        
        result2 = self.runbzr("log -r 1..")[0]
        self.assertEquals(result2, result)
