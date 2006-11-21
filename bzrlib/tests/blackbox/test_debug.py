# Copyright (C) 2006 Canonical Ltd
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

"""Blackbox tests for -D debug options"""

import os

from bzrlib.tests import TestCase

class TestDebugOption(TestCase):

    def test_dash_derror(self):
        """With -Derror, tracebacks are shown even for user errors"""
        out, err = self.run_bzr("-Derror", "branch", "nonexistent-location",
                retcode=3)
        # error output should contain a traceback
        self.assertContainsRe(err, "    raise errors\.NotBranchError")


