# Copyright (C) 2010 Canonical Ltd
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


"""Black-box tests for bzr config."""

import os

from bzrlib import (
    config,
    tests,
    )
from bzrlib.tests import script


class TestEmptyConfig(tests.TestCaseWithTransport):

    def test_no_config(self):
        out, err = self.run_bzr(['config'])
        self.assertEquals('', out)
        self.assertEquals('', err)

    def test_all_variables_no_config(self):
        out, err = self.run_bzr(['config', '*'])
        self.assertEquals('', out)
        self.assertEquals('', err)


class TestConfigDisplay(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConfigDisplay, self).setUp()
        # All the test can chose to test in a branch or outside of it
        # (defaulting to location='.' by using '-d tree'. We create the 3
        # canonnical configs and each test can set whatever option it sees fit.
        self.tree = self.make_branch_and_tree('tree')
        self.branch_config = config.BranchConfig(self.tree.branch)
        self.locations_config = config.LocationConfig(self.tree.basedir)
        self.global_config = config.GlobalConfig()

    def test_global_config(self):
        self.global_config.set_user_option('hello', 'world')
        script.run_script(self, '''
$ bzr config -d tree
bazaar:
  hello = world
''')

    def test_locations_config_for_branch(self):
        self.locations_config.set_user_option('hello', 'world')
        self.branch_config.set_user_option('hello', 'you')
        script.run_script(self, '''
$ bzr config -d tree
locations:
  hello = world
branch:
  hello = you
''')

    def test_locations_config_outside_branch(self):
        self.global_config.set_user_option('hello', 'world')
        self.locations_config.set_user_option('hello', 'world')
        script.run_script(self, '''
$ bzr config
bazaar:
  hello = world
''')
