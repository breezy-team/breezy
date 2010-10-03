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
    errors,
    tests,
    )
from bzrlib.tests import (
    script,
    # FIXME: Importing the 'other' test_config to use TestWithConfigs hints
    # that we really need a fixture here -- vila 20101002
    test_config as _t_config,
    )

class TestEmptyConfig(tests.TestCaseWithTransport):

    def test_no_config(self):
        out, err = self.run_bzr(['config'])
        self.assertEquals('', out)
        self.assertEquals('', err)

    def test_all_variables_no_config(self):
        out, err = self.run_bzr(['config', '*'])
        self.assertEquals('', out)
        self.assertEquals('', err)


class TestConfigDisplay(_t_config.TestWithConfigs):

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


class TestConfigSet(_t_config.TestWithConfigs):

    def test_unknown_config(self):
        self.run_bzr(['config', '--force', 'moon', 'hello=world'], retcode=3)

    def test_global_config_outside_branch(self):
        script.run_script(self, '''
$ bzr config --force bazaar hello=world
$ bzr config -d tree hello
bazaar:
  hello = world
''')

    def test_global_config_inside_branch(self):
        script.run_script(self, '''
$ bzr config -d tree --force bazaar hello=world
$ bzr config -d tree hello
bazaar:
  hello = world
''')

    def test_locations_config_inside_branch(self):
        script.run_script(self, '''
$ bzr config -d tree --force locations hello=world
$ bzr config -d tree hello
locations:
  hello = world
''')

    def test_branch_config_default(self):
        script.run_script(self, '''
$ bzr config -d tree hello=world
$ bzr config -d tree hello
branch:
  hello = world
''')

    def test_branch_config_forcing_branch(self):
        script.run_script(self, '''
$ bzr config -d tree --force branch hello=world
$ bzr config -d tree hello
branch:
  hello = world
''')
