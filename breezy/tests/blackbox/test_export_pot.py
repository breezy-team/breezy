# Copyright (C) 2011 Canonical Ltd
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


"""External tests of 'brz export-pot'."""

import inspect
import os

from breezy import commands, option, registry
from breezy.tests import TestCaseWithMemoryTransport

from ..features import PluginLoadedFeature

_protocols = registry.Registry()
_protocols.register("new", 1, "Current protocol.")


class _Hider:
    hidden = True


_protocols.register("old", 0, "Legacy protocol.", info=_Hider())


class cmd_pot_demo(commands.Command):
    """A sample command.

    :Usage:
        brz pot-demo

    :Examples:
        Example 1::

            cmd arg1

    Blah Blah Blah
    """

    takes_options = [
        "revision",
        option.Option("helpful", help="Pot demo info."),
        option.Option("unseen", help="Pot demo hidden.", hidden=True),
        option.Option("again", help="Pot demo repeated."),
        option.Option("twice", help="Pot demo repeated."),
        option.RegistryOption(
            "protocol",
            "Pot demo talking.",
            _protocols,
            value_switches=True,
            enum_switch=False,
            title="Pot demo choose!",
        ),
    ]

    def run(self, **kwargs):
        pass


class TestExportPot(TestCaseWithMemoryTransport):
    def test_export_pot(self):
        out, err = self.run_bzr("export-pot")
        self.assertContainsRe(err, "Exporting messages from builtin command: add")
        self.assertContainsRe(
            out,
            "help of 'change' option\n"
            'msgid "Select changes introduced by the specified revision.',
        )

    def test_export_pot_plugin_unknown(self):
        _out, err = self.run_bzr("export-pot --plugin=lalalala", retcode=3)
        self.assertContainsRe(err, "ERROR: Plugin lalalala is not loaded")

    def test_export_pot_plugin(self):
        self.requireFeature(PluginLoadedFeature("launchpad"))
        out, err = self.run_bzr("export-pot --plugin=launchpad")
        self.assertContainsRe(
            err, "Exporting messages from plugin command: launchpad-login in launchpad"
        )
        self.assertContainsRe(out, 'msgid "Show or set the Launchpad user ID."')


class TestExportPotDetails(TestCaseWithMemoryTransport):
    def setUp(self):
        super().setUp()
        commands.builtin_command_registry.register(cmd_pot_demo)
        self.addCleanup(commands.builtin_command_registry.remove, "pot-demo")

    def location(self, text, offset=0):
        """The reference for the line of this file containing text."""
        path = inspect.getsourcefile(cmd_pot_demo)
        with open(path) as f:
            for lineno, line in enumerate(f, 1):
                if text in line:
                    return f"#: {os.path.relpath(path)}:{lineno + offset}\n"
        raise AssertionError(f"{text!r} not in {path}")

    def test_command_help(self):
        out, err = self.run_bzr("export-pot")
        self.assertContainsRe(err, "Exporting messages from builtin command: pot-demo")
        self.assertContainsString(
            out,
            self.location('"""A sample command.')
            + 'msgid "A sample command."\nmsgstr ""\n\n'
            # The :Usage: paragraph is left out, and the line number does
            # not advance past it.
            + self.location('"""A sample command.', 2)
            + 'msgid ""\n'
            '":Examples:\\n"\n'
            '"    Example 1::"\n'
            'msgstr ""\n\n',
        )
        self.assertContainsString(out, 'msgid "        cmd arg1"\n')
        self.assertContainsString(out, 'msgid "Blah Blah Blah"\n')
        self.assertNotContainsString(out, "brz pot-demo")

    def test_command_options(self):
        out, _ = self.run_bzr("export-pot")
        self.assertContainsString(
            out,
            self.location('"Pot demo info."')
            + "# help of 'helpful' option of 'pot-demo' command\n"
            'msgid "Pot demo info."\n',
        )
        self.assertContainsString(
            out,
            self.location('"Pot demo choose!"')
            + "# title of 'protocol' option of 'pot-demo' command\n"
            'msgid "Pot demo choose!"\n',
        )
        self.assertContainsString(
            out,
            self.location('"Pot demo talking."')
            + "# help of 'protocol' option of 'pot-demo' command\n"
            'msgid "Pot demo talking."\n',
        )
        self.assertContainsString(
            out,
            "# help of 'protocol=new' option of 'pot-demo' command\n"
            'msgid "Current protocol."\n',
        )
        self.assertNotContainsString(out, "Pot demo hidden.")
        self.assertNotContainsString(out, "protocol=old")

    def test_duplicates(self):
        out, _ = self.run_bzr("export-pot")
        self.assertEqual(1, out.count('msgid "Pot demo repeated."'))
        out, _ = self.run_bzr("export-pot --include-duplicates")
        self.assertEqual(2, out.count('msgid "Pot demo repeated."'))

    def test_error_messages(self):
        out, err = self.run_bzr("export-pot")
        self.assertContainsRe(err, "Exporting message from error: NotBranchError")
        self.assertContainsRe(
            out,
            r'#: [^\n]*breezy/errors.py:\d+\nmsgid "Not a branch: \\"%\(path\)s\\"%\(detail\)s\."',
        )

    def test_help_topics(self):
        out, _ = self.run_bzr("export-pot")
        self.assertContainsString(
            out,
            '#: dummy/help_topics/bugs/summary.txt:1\nmsgid "Bug tracker settings"\n',
        )
        self.assertContainsRe(
            out,
            r"#: dummy/help_topics/bugs/detail.txt:\d+\n"
            'msgid ""\n"The ``--fixes`` option',
        )
