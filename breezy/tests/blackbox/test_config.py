# Copyright (C) 2010, 2011, 2012, 2016 Canonical Ltd
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


"""Black-box tests for brz config."""

from ... import (
    config,
    tests,
    )
from .. import (
    script,
    test_config as _t_config,
    )


class TestWithoutConfig(tests.TestCaseWithTransport):

    def test_config_all(self):
        out, err = self.run_bzr(['config'])
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_remove_unknown_option(self):
        self.run_bzr_error(['The "file" configuration option does not exist', ],
                           ['config', '--remove', 'file'])

    def test_all_remove_exclusive(self):
        self.run_bzr_error(['--all and --remove are mutually exclusive.', ],
                           ['config', '--remove', '--all'])

    def test_all_set_exclusive(self):
        self.run_bzr_error(['Only one option can be set.', ],
                           ['config', '--all', 'hello=world'])

    def test_remove_no_option(self):
        self.run_bzr_error(['--remove expects an option to remove.', ],
                           ['config', '--remove'])

    def test_unknown_option(self):
        self.run_bzr_error(['The "file" configuration option does not exist', ],
                           ['config', 'file'])

    def test_unexpected_regexp(self):
        self.run_bzr_error(
            ['The "\\*file" configuration option does not exist', ],
            ['config', '*file'])

    def test_wrong_regexp(self):
        self.run_bzr_error(
            ['Invalid pattern\\(s\\) found. "\\*file" nothing to repeat', ],
            ['config', '--all', '*file'])


class TestConfigDisplay(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConfigDisplay, self).setUp()
        _t_config.create_configs(self)

    def test_multiline_all_values(self):
        self.breezy_config.set_user_option('multiline', '1\n2\n')
        # Fallout from bug 710410, the triple quotes have been toggled
        script.run_script(self, '''\
            $ brz config -d tree
            breezy:
              [DEFAULT]
              multiline = """1
            2
            """
            ''')

    def test_multiline_value_only(self):
        self.breezy_config.set_user_option('multiline', '1\n2\n')
        # Fallout from bug 710410, the triple quotes have been toggled
        script.run_script(self, '''\
            $ brz config -d tree multiline
            """1
            2
            """
            ''')

    def test_list_value_all(self):
        config.option_registry.register(config.ListOption('list'))
        self.addCleanup(config.option_registry.remove, 'list')
        self.breezy_config.set_user_option('list', [1, 'a', 'with, a comma'])
        script.run_script(self, '''\
            $ brz config -d tree
            breezy:
              [DEFAULT]
              list = 1, a, "with, a comma"
            ''')

    def test_list_value_one(self):
        config.option_registry.register(config.ListOption('list'))
        self.addCleanup(config.option_registry.remove, 'list')
        self.breezy_config.set_user_option('list', [1, 'a', 'with, a comma'])
        script.run_script(self, '''\
            $ brz config -d tree list
            1, a, "with, a comma"
            ''')

    def test_registry_value_all(self):
        self.breezy_config.set_user_option('transform.orphan_policy',
                                           u'move')
        script.run_script(self, '''\
            $ brz config -d tree
            breezy:
              [DEFAULT]
              transform.orphan_policy = move
            ''')

    def test_registry_value_one(self):
        self.breezy_config.set_user_option('transform.orphan_policy',
                                           u'move')
        script.run_script(self, '''\
            $ brz config -d tree transform.orphan_policy
            move
            ''')

    def test_breezy_config(self):
        self.breezy_config.set_user_option('hello', 'world')
        script.run_script(self, '''\
            $ brz config -d tree
            breezy:
              [DEFAULT]
              hello = world
            ''')

    def test_locations_config_for_branch(self):
        self.locations_config.set_user_option('hello', 'world')
        self.branch_config.set_user_option('hello', 'you')
        script.run_script(self, '''\
            $ brz config -d tree
            locations:
              [.../tree]
              hello = world
            branch:
              hello = you
            ''')

    def test_locations_config_outside_branch(self):
        self.breezy_config.set_user_option('hello', 'world')
        self.locations_config.set_user_option('hello', 'world')
        script.run_script(self, '''\
            $ brz config
            breezy:
              [DEFAULT]
              hello = world
            ''')

    def test_cmd_line(self):
        self.breezy_config.set_user_option('hello', 'world')
        script.run_script(self, '''\
            $ brz config -Ohello=bzr
            cmdline:
              hello = bzr
            breezy:
              [DEFAULT]
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
            $ brz config -d tree --all url
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
            $ brz config -d tree file
            locations
            ''')

    def test_active_in_breezy(self):
        script.run_script(self, '''\
            $ brz config -d tree --scope breezy file
            breezy
            ''')

    def test_active_in_branch(self):
        # We need to delete the locations definition that overrides the branch
        # one
        script.run_script(self, '''\
            $ brz config -d tree --scope locations --remove file
            $ brz config -d tree file
            branch
            ''')


class TestConfigSetOption(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConfigSetOption, self).setUp()
        _t_config.create_configs(self)

    def test_unknown_config(self):
        self.run_bzr_error(['The "moon" configuration does not exist'],
                           ['config', '--scope', 'moon', 'hello=world'])

    def test_breezy_config_outside_branch(self):
        script.run_script(self, '''\
            $ brz config --scope breezy hello=world
            $ brz config -d tree --all hello
            breezy:
              [DEFAULT]
              hello = world
            ''')

    def test_breezy_config_inside_branch(self):
        script.run_script(self, '''\
            $ brz config -d tree --scope breezy hello=world
            $ brz config -d tree --all hello
            breezy:
              [DEFAULT]
              hello = world
            ''')

    def test_locations_config_inside_branch(self):
        script.run_script(self, '''\
            $ brz config -d tree --scope locations hello=world
            $ brz config -d tree --all hello
            locations:
              [.../work/tree]
              hello = world
            ''')

    def test_branch_config_default(self):
        script.run_script(self, '''\
            $ brz config -d tree hello=world
            $ brz config -d tree --all hello
            branch:
              hello = world
            ''')

    def test_branch_config_forcing_branch(self):
        script.run_script(self, '''\
            $ brz config -d tree --scope branch hello=world
            $ brz config -d tree --all hello
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

    def test_breezy_config_outside_branch(self):
        script.run_script(self, '''\
            $ brz config --scope breezy --remove file
            $ brz config -d tree --all file
            locations:
              [.../work/tree]
              file = locations
            branch:
              file = branch
            ''')

    def test_breezy_config_inside_branch(self):
        script.run_script(self, '''\
            $ brz config -d tree --scope breezy --remove file
            $ brz config -d tree --all file
            locations:
              [.../work/tree]
              file = locations
            branch:
              file = branch
            ''')

    def test_locations_config_inside_branch(self):
        script.run_script(self, '''\
            $ brz config -d tree --scope locations --remove file
            $ brz config -d tree --all file
            branch:
              file = branch
            breezy:
              [DEFAULT]
              file = breezy
            ''')

    def test_branch_config_default(self):
        script.run_script(self, '''\
            $ brz config -d tree --scope locations --remove file
            $ brz config -d tree --all file
            branch:
              file = branch
            breezy:
              [DEFAULT]
              file = breezy
            ''')
        script.run_script(self, '''\
            $ brz config -d tree --remove file
            $ brz config -d tree --all file
            breezy:
              [DEFAULT]
              file = breezy
            ''')

    def test_branch_config_forcing_branch(self):
        script.run_script(self, '''\
            $ brz config -d tree --scope branch --remove file
            $ brz config -d tree --all file
            locations:
              [.../work/tree]
              file = locations
            breezy:
              [DEFAULT]
              file = breezy
            ''')
        script.run_script(self, '''\
            $ brz config -d tree --scope locations --remove file
            $ brz config -d tree --all file
            breezy:
              [DEFAULT]
              file = breezy
            ''')


class TestConfigDirectory(tests.TestCaseWithTransport):

    def test_parent_alias(self):
        t = self.make_branch_and_tree('base')
        t.branch.get_config_stack().set('test', 'base')
        clone = t.branch.controldir.sprout('clone').open_branch()
        clone.get_config_stack().set('test', 'clone')
        out, err = self.run_bzr(['config', '-d', ':parent', 'test'],
                                working_dir='clone')
        self.assertEqual('base\n', out)
