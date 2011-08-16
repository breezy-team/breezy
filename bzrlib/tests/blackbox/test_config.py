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
    test_config as _t_config,
    )

class TestWithoutConfig(tests.TestCaseWithTransport):

    def test_config_all(self):
        out, err = self.run_bzr(['config'])
        self.assertEquals('', out)
        self.assertEquals('', err)

    def test_remove_unknown_option(self):
        self.run_bzr_error(['The "file" configuration option does not exist',],
                           ['config', '--remove', 'file'])

    def test_all_remove_exclusive(self):
        self.run_bzr_error(['--all and --remove are mutually exclusive.',],
                           ['config', '--remove', '--all'])

    def test_all_set_exclusive(self):
        self.run_bzr_error(['Only one option can be set.',],
                           ['config', '--all', 'hello=world'])

    def test_remove_no_option(self):
        self.run_bzr_error(['--remove expects an option to remove.',],
                           ['config', '--remove'])

    def test_unknown_option(self):
        self.run_bzr_error(['The "file" configuration option does not exist',],
                           ['config', 'file'])

    def test_unexpected_regexp(self):
        self.run_bzr_error(
            ['The "\*file" configuration option does not exist',],
            ['config', '*file'])

    def test_wrong_regexp(self):
        self.run_bzr_error(
            ['Invalid pattern\(s\) found. "\*file" nothing to repeat',],
            ['config', '--all', '*file'])



class TestConfigDisplay(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConfigDisplay, self).setUp()
        _t_config.create_configs(self)

    def test_multiline_all_values(self):
        self.bazaar_config.set_user_option('multiline', '1\n2\n')
        # Fallout from bug 710410, the triple quotes have been toggled
        script.run_script(self, '''\
            $ bzr config -d tree
            bazaar:
              multiline = """1
            2
            """
            ''')

    def test_multiline_value_only(self):
        self.bazaar_config.set_user_option('multiline', '1\n2\n')
        # Fallout from bug 710410, the triple quotes have been toggled
        script.run_script(self, '''\
            $ bzr config -d tree multiline
            """1
            2
            """
            ''')

    def test_list_all_values(self):
        self.bazaar_config.set_user_option('list', [1, 'a', 'with, a comma'])
        script.run_script(self, '''\
            $ bzr config -d tree
            bazaar:
              list = 1, a, "with, a comma"
            ''')

    def test_list_value_only(self):
        self.bazaar_config.set_user_option('list', [1, 'a', 'with, a comma'])
        script.run_script(self, '''\
            $ bzr config -d tree list
            1, a, "with, a comma"
            ''')

    def test_bazaar_config(self):
        self.bazaar_config.set_user_option('hello', 'world')
        script.run_script(self, '''\
            $ bzr config -d tree
            bazaar:
              hello = world
            ''')

    def test_locations_config_for_branch(self):
        self.locations_config.set_user_option('hello', 'world')
        self.branch_config.set_user_option('hello', 'you')
        script.run_script(self, '''\
            $ bzr config -d tree
            locations:
              [.../tree]
              hello = world
            branch:
              hello = you
            ''')

    def test_locations_config_outside_branch(self):
        self.bazaar_config.set_user_option('hello', 'world')
        self.locations_config.set_user_option('hello', 'world')
        script.run_script(self, '''\
            $ bzr config
            bazaar:
              hello = world
            ''')

class TestConfigDisplayWithPolicy(tests.TestCaseWithTransport):

    def test_location_with_policy(self):
        # LocationConfig is the only one dealing with policies so far.
        self.make_branch_and_tree('tree')
        config_text = """\
[%(dir)s]
url = dir
url:policy = appendpath
[%(dir)s/tree]
url = tree
""" % {'dir': self.test_dir}
        # We don't use the config directly so we save it to disk
        config.LocationConfig.from_string(config_text, 'tree', save=True)
        # policies are displayed with their options since they are part of
        # their definition, likewise the path is not appended, we are just
        # presenting the relevant portions of the config files
        script.run_script(self, '''\
            $ bzr config -d tree --all url
            locations:
              [.../work/tree]
              url = tree
              [.../work]
              url = dir
              url:policy = appendpath
            ''')


class TestConfigActive(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConfigActive, self).setUp()
        _t_config.create_configs_with_file_option(self)

    def test_active_in_locations(self):
        script.run_script(self, '''\
            $ bzr config -d tree file
            locations
            ''')

    def test_active_in_bazaar(self):
        script.run_script(self, '''\
            $ bzr config -d tree --scope bazaar file
            bazaar
            ''')

    def test_active_in_branch(self):
        # We need to delete the locations definition that overrides the branch
        # one
        script.run_script(self, '''\
            $ bzr config -d tree --remove file
            $ bzr config -d tree file
            branch
            ''')


class TestConfigSetOption(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConfigSetOption, self).setUp()
        _t_config.create_configs(self)

    def test_unknown_config(self):
        self.run_bzr_error(['The "moon" configuration does not exist'],
                           ['config', '--scope', 'moon', 'hello=world'])

    def test_bazaar_config_outside_branch(self):
        script.run_script(self, '''\
            $ bzr config --scope bazaar hello=world
            $ bzr config -d tree --all hello
            bazaar:
              hello = world
            ''')

    def test_bazaar_config_inside_branch(self):
        script.run_script(self, '''\
            $ bzr config -d tree --scope bazaar hello=world
            $ bzr config -d tree --all hello
            bazaar:
              hello = world
            ''')

    def test_locations_config_inside_branch(self):
        script.run_script(self, '''\
            $ bzr config -d tree --scope locations hello=world
            $ bzr config -d tree --all hello
            locations:
              [.../work/tree]
              hello = world
            ''')

    def test_branch_config_default(self):
        script.run_script(self, '''\
            $ bzr config -d tree hello=world
            $ bzr config -d tree --all hello
            branch:
              hello = world
            ''')

    def test_branch_config_forcing_branch(self):
        script.run_script(self, '''\
            $ bzr config -d tree --scope branch hello=world
            $ bzr config -d tree --all hello
            branch:
              hello = world
            ''')


class TestConfigRemoveOption(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConfigRemoveOption, self).setUp()
        _t_config.create_configs_with_file_option(self)

    def test_unknown_config(self):
        self.run_bzr_error(['The "moon" configuration does not exist'],
                           ['config', '--scope', 'moon', '--remove', 'file'])

    def test_bazaar_config_outside_branch(self):
        script.run_script(self, '''\
            $ bzr config --scope bazaar --remove file
            $ bzr config -d tree --all file
            locations:
              [.../work/tree]
              file = locations
            branch:
              file = branch
            ''')

    def test_bazaar_config_inside_branch(self):
        script.run_script(self, '''\
            $ bzr config -d tree --scope bazaar --remove file
            $ bzr config -d tree --all file
            locations:
              [.../work/tree]
              file = locations
            branch:
              file = branch
            ''')

    def test_locations_config_inside_branch(self):
        script.run_script(self, '''\
            $ bzr config -d tree --scope locations --remove file
            $ bzr config -d tree --all file
            branch:
              file = branch
            bazaar:
              file = bazaar
            ''')

    def test_branch_config_default(self):
        script.run_script(self, '''\
            $ bzr config -d tree --remove file
            $ bzr config -d tree --all file
            branch:
              file = branch
            bazaar:
              file = bazaar
            ''')
        script.run_script(self, '''\
            $ bzr config -d tree --remove file
            $ bzr config -d tree --all file
            bazaar:
              file = bazaar
            ''')

    def test_branch_config_forcing_branch(self):
        script.run_script(self, '''\
            $ bzr config -d tree --scope branch --remove file
            $ bzr config -d tree --all file
            locations:
              [.../work/tree]
              file = locations
            bazaar:
              file = bazaar
            ''')
        script.run_script(self, '''\
            $ bzr config -d tree --remove file
            $ bzr config -d tree --all file
            bazaar:
              file = bazaar
            ''')
