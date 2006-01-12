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


"""Black-box tests for bzr status.
"""

import os

import bzrlib
from bzrlib.tests.blackbox import ExternalBase


class TestStatus(ExternalBase):

    def test_status(self):
        self.runbzr("init")
        self.build_tree(['hello.txt'])
        result = self.runbzr("status")
        self.assert_("unknown:\n  hello.txt\n" in result, result)
        self.runbzr("add hello.txt")
        result = self.runbzr("status")
        self.assert_("added:\n  hello.txt\n" in result, result)
        self.runbzr("commit -m added")
        result = self.runbzr("status -r 0..1")
        self.assert_("added:\n  hello.txt\n" in result, result)
        self.build_tree(['world.txt'])
        result = self.runbzr("status -r 0")
        self.assert_("added:\n  hello.txt\n" \
                     "unknown:\n  world.txt\n" in result, result)

        result2 = self.runbzr("status -r 0..")
        self.assertEquals(result2, result)
