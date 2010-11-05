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


"""Tests for how many modules are loaded in executing various commands."""

from testtools import content

from bzrlib.plugin import (
    are_plugins_disabled,
    )

from bzrlib.tests import (
    TestCaseWithTransport,
    )


class TestImportTariffs(TestCaseWithTransport):

    """Check how many modules are loaded for some representative scenarios.

    See the Testing Guide in the developer documentation for more explanation.
    """

    def run_command_check_imports(self, args, forbidden_imports):
        """Run bzr ARGS in a subprocess and check its imports.

        This is fairly expensive because we start a subprocess, so we aim to
        cover representative rather than exhaustive cases.

        :param forbidden_imports: List of fully-qualified Python module names
            that should not be loaded while running this command.
        """
        # We use PYTHON_VERBOSE rather than --profile-importts because in
        # experimentation the profile-imports output seems to not always show
        # the modules you'd expect; this can be debugged but python -v seems
        # more likely to always show everything.  And we use the environment
        # variable rather than 'python -v' in the hope it will work even if
        # bzr is frozen and python is not explicitly specified. -- mbp 20100208
        #
        # Normally we want test isolation from the real $HOME but here we
        # explicitly do want to test against things installed there, therefore
        # we pass it through.
        env_changes = dict(PYTHONVERBOSE='1')
        for name in ['BZR_HOME', 'BZR_PLUGIN_PATH',
                     'BZR_DISABLE_PLUGINS', 'BZR_PLUGINS_AT',
                     'HOME',]:
            env_changes[name] = self._old_env.get(name)
        out, err = self.run_bzr_subprocess(args,
            allow_plugins=(not are_plugins_disabled()),
            env_changes=env_changes)

        self.addDetail('subprocess_stderr',
            content.Content(content.ContentType("text", "plain"),
                lambda:[err]))

        bad_modules = []
        for module_name in forbidden_imports:
            if err.find("\nimport %s " % module_name) != -1:
                bad_modules.append(module_name)

        if bad_modules:
            self.fail("command %r loaded forbidden modules %r"
                % (args, bad_modules))
        return out, err

    def test_import_tariffs_working(self):
        # check some guaranteed-true and false imports to be sure we're
        # measuring correctly
        self.make_branch_and_tree('.')
        self.run_command_check_imports(['st'],
            ['nonexistentmodulename', 'anothernonexistentmodule'])
        self.assertRaises(AssertionError,
            self.run_command_check_imports,
            ['st'],
            ['bzrlib.tree'])

    def test_simple_local(self):
        # 'st' in a working tree shouldn't need many modules
        self.make_branch_and_tree('.')
        self.run_command_check_imports(['st'], [
            'bzrlib.bundle.commands',
            'bzrlib.cmd_version_info',
            'bzrlib.foreign',
            'bzrlib.merge3',
            'bzrlib.patiencediff',
            'bzrlib.remote',
            'bzrlib.sign_my_commits',
            'bzrlib.smart',
            'bzrlib.transform',
            'kerberos',
            'smtplib',
            'tarfile',
            ])
        # TODO: similar test for repository-only operations, checking we avoid
        # loading wt-specific stuff
        #
        # See https://bugs.launchpad.net/bzr/+bug/553017

    def test_help_commands(self):
        # See https://bugs.launchpad.net/bzr/+bug/663773
        self.run_command_check_imports(['help', 'commands'], [
            'testtools',
            ])
