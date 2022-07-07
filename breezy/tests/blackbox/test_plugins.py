# Copyright (C) 2005-2012, 2016 Canonical Ltd
# Copyright (C) 2017-2018 Breezy developers
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

"""Blackbox tests for plugins behaviour and commands."""

import os

from ... import (
    commands,
    )
from ..test_plugins import (
    BaseTestPlugins,
    )


class TestPluginHelp(BaseTestPlugins):

    def run_bzr_utf8_out(self, *args, **kwargs):
        out, _ = self.run_bzr(*args, **kwargs)
        return out

    def split_help_commands(self):
        help = {}
        current = None
        out = self.run_bzr_utf8_out('--no-plugins help commands')
        for line in out.splitlines():
            if not line.startswith(' '):
                current = line.split()[0]
            help[current] = help.get(current, '') + line

        return help

    def test_plugin_help_builtins_unaffected(self):
        # Check we don't get false positives
        help_commands = self.split_help_commands()
        for cmd_name in commands.builtin_command_names():
            if cmd_name in commands.plugin_command_names():
                continue
            try:
                help = commands.get_cmd_object(cmd_name).get_help_text()
            except NotImplementedError:
                # some commands have no help
                pass
            else:
                self.assertNotContainsRe(help, 'plugin "[^"]*"')

            if cmd_name in help_commands:
                # some commands are hidden
                help = help_commands[cmd_name]
                self.assertNotContainsRe(help, 'plugin "[^"]*"')

    def test_plugin_help_shows_plugin(self):
        # Create a test plugin
        os.mkdir('plugin_test')
        source = (
            "from breezy import commands\n"
            "class cmd_myplug(commands.Command):\n"
            "    __doc__ = '''Just a simple test plugin.'''\n"
            "    aliases = ['mplg']\n"
            "    def run(self):\n"
            "        print ('Hello from my plugin')\n"
        )
        self.create_plugin('myplug', source, 'plugin_test')

        # Check its help
        self.load_with_paths(['plugin_test'])
        myplug = self.plugins['myplug'].module
        commands.register_command(myplug.cmd_myplug)
        self.addCleanup(commands.plugin_cmds.remove, 'myplug')
        help = self.run_bzr_utf8_out('help myplug')
        self.assertContainsRe(help, 'plugin "myplug"')
        help = self.split_help_commands()['myplug']
        self.assertContainsRe(help, '\\[myplug\\]')
