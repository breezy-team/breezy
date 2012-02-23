# Copyright (C) 2010, 2011 Canonical Ltd
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

import os

from testtools import content

from bzrlib import (
    plugins as _mod_plugins,
    trace,
    )
from bzrlib.controldir import ControlDir
from bzrlib.smart import medium
from bzrlib.transport import remote

from bzrlib.plugin import (
    are_plugins_disabled,
    )

from bzrlib.tests import (
    TestCaseWithTransport,
    )

old_format_modules = [
    'bzrlib.repofmt.knitrepo',
    'bzrlib.repofmt.knitpack_repo',
    'bzrlib.plugins.weave_fmt.branch',
    'bzrlib.plugins.weave_fmt.bzrdir',
    'bzrlib.plugins.weave_fmt.repository',
    'bzrlib.plugins.weave_fmt.workingtree',
    'bzrlib.weave',
    'bzrlib.weavefile',
    'bzrlib.xml4',
    'bzrlib.xml5',
    'bzrlib.xml6',
    'bzrlib.xml7',
    ]


class ImportTariffTestCase(TestCaseWithTransport):
    """Check how many modules are loaded for some representative scenarios.

    See the Testing Guide in the developer documentation for more explanation.


    We must respect the setup used by the selftest command regarding
    plugins. This allows the user to control which plugins are in effect while
    running these tests and respect the import policies defined here.

    When failures are encountered for a given plugin, they can generally be
    addressed by using lazy import or lazy hook registration.
    """

    def setUp(self):
        self.preserved_env_vars = {}
        for name in ('BZR_PLUGIN_PATH', 'BZR_DISABLE_PLUGINS', 'BZR_PLUGINS_AT'
                     ):
            self.preserved_env_vars[name] = os.environ.get(name)
        super(ImportTariffTestCase, self).setUp()

    def start_bzr_subprocess_with_import_check(self, args, stderr_file=None):
        """Run a bzr process and capture the imports.

        This is fairly expensive because we start a subprocess, so we aim to
        cover representative rather than exhaustive cases.
        """
        # We use PYTHON_VERBOSE rather than --profile-imports because in
        # experimentation the profile-imports output seems to not always show
        # the modules you'd expect; this can be debugged but python -v seems
        # more likely to always show everything.  And we use the environment
        # variable rather than 'python -v' in the hope it will work even if
        # bzr is frozen and python is not explicitly specified. -- mbp 20100208
        env_changes = dict(PYTHONVERBOSE='1', **self.preserved_env_vars)
        trace.mutter('Setting env for bzr subprocess: %r', env_changes)
        kwargs = dict(env_changes=env_changes,
                      allow_plugins=(not are_plugins_disabled()))
        if stderr_file:
            # We don't want to update the whole call chain so we insert stderr
            # *iff* we need to
            kwargs['stderr'] = stderr_file
        return self.start_bzr_subprocess(args, **kwargs)

    def check_forbidden_modules(self, err, forbidden_imports):
        """Check for forbidden modules in stderr.

        :param err: Standard error
        :param forbidden_imports: List of forbidden modules
        """
        self.addDetail('subprocess_stderr',
            content.Content(content.ContentType("text", "plain"),
                lambda:[err]))

        bad_modules = []
        for module_name in forbidden_imports:
            if err.find("\nimport %s " % module_name) != -1:
                bad_modules.append(module_name)

        if bad_modules:
            self.fail("command loaded forbidden modules %r"
                % (bad_modules,))

    def finish_bzr_subprocess_with_import_check(self, process,
            args, forbidden_imports):
        """Finish subprocess and check specific modules have not been
        imported.

        :param forbidden_imports: List of fully-qualified Python module names
            that should not be loaded while running this command.
        """
        (out, err) = self.finish_bzr_subprocess(process,
            universal_newlines=False, process_args=args)
        self.check_forbidden_modules(err, forbidden_imports)
        return out, err

    def run_command_check_imports(self, args, forbidden_imports):
        """Run bzr ARGS in a subprocess and check its imports.

        This is fairly expensive because we start a subprocess, so we aim to
        cover representative rather than exhaustive cases.

        :param forbidden_imports: List of fully-qualified Python module names
            that should not be loaded while running this command.
        """
        process = self.start_bzr_subprocess_with_import_check(args)
        self.finish_bzr_subprocess_with_import_check(process, args,
            forbidden_imports)


class TestImportTariffs(ImportTariffTestCase):
    """Basic import tariff tests for some common bzr commands"""

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
        # 'st' in a default format working tree shouldn't need many modules
        self.make_branch_and_tree('.')
        self.run_command_check_imports(['st'], [
            'bzrlib.annotate',
            'bzrlib.atomicfile',
            'bzrlib.bugtracker',
            'bzrlib.bundle.commands',
            'bzrlib.cmd_version_info',
            'bzrlib.externalcommand',
            'bzrlib.filters',
            'bzrlib.hashcache',
            # foreign branch plugins import the foreign_vcs_registry from 
            # bzrlib.foreign so it can't be blacklisted
            'bzrlib.gpg',
            'bzrlib.info',
            'bzrlib.knit',
            'bzrlib.merge3',
            'bzrlib.merge_directive',
            'bzrlib.msgeditor',
            'bzrlib.patiencediff',
            'bzrlib.remote',
            'bzrlib.rules',
            'bzrlib.sign_my_commits',
            'bzrlib.smart',
            'bzrlib.smart.client',
            'bzrlib.smart.medium',
            'bzrlib.smart.server',
            'bzrlib.transform',
            'bzrlib.version_info_formats.format_rio',
            'bzrlib.xml_serializer',
            'bzrlib.xml8',
            'getpass',
            'kerberos',
            'ssl',
            'socket',
            'smtplib',
            'tarfile',
            'tempfile',
            'termios',
            'tty',
            'urllib',
            ] + old_format_modules)
        # TODO: similar test for repository-only operations, checking we avoid
        # loading wt-specific stuff
        #
        # See https://bugs.launchpad.net/bzr/+bug/553017

    def test_help_commands(self):
        # See https://bugs.launchpad.net/bzr/+bug/663773
        self.run_command_check_imports(['help', 'commands'], [
            'testtools',
            ])

    def test_simple_serve(self):
        # 'serve' in a default format working tree shouldn't need many modules
        tree = self.make_branch_and_tree('.')
        # Capture the bzr serve process' stderr in a file to avoid deadlocks
        # while the smart client interacts with it.
        stderr_file = open('bzr-serve.stderr', 'w')
        process = self.start_bzr_subprocess_with_import_check(['serve',
            '--inet', '-d', tree.basedir], stderr_file=stderr_file)
        url = 'bzr://localhost/'
        self.permit_url(url)
        client_medium = medium.SmartSimplePipesClientMedium(
            process.stdout, process.stdin, url)
        transport = remote.RemoteTransport(url, medium=client_medium)
        branch = ControlDir.open_from_transport(transport).open_branch()
        process.stdin.close()
        # Hide stdin from the subprocess module, so it won't fail to close it.
        process.stdin = None
        (out, err) = self.finish_bzr_subprocess(process,
            universal_newlines=False)
        stderr_file.close()
        with open('bzr-serve.stderr', 'r') as stderr_file:
            err = stderr_file.read()
        self.check_forbidden_modules(err,
            ['bzrlib.annotate',
            'bzrlib.atomicfile',
            'bzrlib.bugtracker',
            'bzrlib.bundle.commands',
            'bzrlib.cmd_version_info',
            'bzrlib.dirstate',
            'bzrlib._dirstate_helpers_py',
            'bzrlib._dirstate_helpers_pyx',
            'bzrlib.externalcommand',
            'bzrlib.filters',
            'bzrlib.hashcache',
            # foreign branch plugins import the foreign_vcs_registry from 
            # bzrlib.foreign so it can't be blacklisted
            'bzrlib.gpg',
            'bzrlib.info',
            'bzrlib.knit',
            'bzrlib.merge3',
            'bzrlib.merge_directive',
            'bzrlib.msgeditor',
            'bzrlib.patiencediff',
            'bzrlib.remote',
            'bzrlib.rules',
            'bzrlib.sign_my_commits',
            'bzrlib.smart.client',
            'bzrlib.transform',
            'bzrlib.version_info_formats.format_rio',
            'bzrlib.workingtree_4',
            'bzrlib.xml_serializer',
            'bzrlib.xml8',
            'getpass',
            'kerberos',
            'smtplib',
            'tarfile',
            'tempfile',
            'termios',
            'tty',
            ] + old_format_modules)
