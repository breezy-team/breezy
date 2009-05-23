# Copyright (C) 2004, 2005 Canonical Ltd
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

from cStringIO import StringIO
import errno
import sys

from bzrlib import (
    builtins,
    commands,
    config,
    errors,
    option,
    tests,
    )
from bzrlib.commands import display_command
from bzrlib.tests import TestSkipped


class TestCommands(tests.TestCase):

    def test_display_command(self):
        """EPIPE message is selectively suppressed"""
        def pipe_thrower():
            raise IOError(errno.EPIPE, "Bogus pipe error")
        self.assertRaises(IOError, pipe_thrower)
        @display_command
        def non_thrower():
            pipe_thrower()
        non_thrower()
        @display_command
        def other_thrower():
            raise IOError(errno.ESPIPE, "Bogus pipe error")
        self.assertRaises(IOError, other_thrower)

    def test_unicode_command(self):
        # This error is thrown when we can't find the command in the
        # list of available commands
        self.assertRaises(errors.BzrCommandError,
                          commands.run_bzr, [u'cmd\xb5'])

    def test_unicode_option(self):
        # This error is actually thrown by optparse, when it
        # can't find the given option
        import optparse
        if optparse.__version__ == "1.5.3":
            raise TestSkipped("optparse 1.5.3 can't handle unicode options")
        self.assertRaises(errors.BzrCommandError,
                          commands.run_bzr, ['log', u'--option\xb5'])

    @staticmethod
    def get_command(options):
        class cmd_foo(commands.Command):
            'Bar'

            takes_options = options

        return cmd_foo()

    def test_help_hidden(self):
        c = self.get_command([option.Option('foo', hidden=True)])
        self.assertNotContainsRe(c.get_help_text(), '--foo')

    def test_help_not_hidden(self):
        c = self.get_command([option.Option('foo', hidden=False)])
        self.assertContainsRe(c.get_help_text(), '--foo')


class TestGetAlias(tests.TestCase):

    def _get_config(self, config_text):
        my_config = config.GlobalConfig()
        config_file = StringIO(config_text.encode('utf-8'))
        my_config._parser = my_config._get_parser(file=config_file)
        return my_config

    def test_simple(self):
        my_config = self._get_config("[ALIASES]\n"
            "diff=diff -r -2..-1\n")
        self.assertEqual([u'diff', u'-r', u'-2..-1'],
            commands.get_alias("diff", config=my_config))

    def test_single_quotes(self):
        my_config = self._get_config("[ALIASES]\n"
            "diff=diff -r -2..-1 --diff-options "
            "'--strip-trailing-cr -wp'\n")
        self.assertEqual([u'diff', u'-r', u'-2..-1', u'--diff-options',
                          u'--strip-trailing-cr -wp'],
                          commands.get_alias("diff", config=my_config))

    def test_double_quotes(self):
        my_config = self._get_config("[ALIASES]\n"
            "diff=diff -r -2..-1 --diff-options "
            "\"--strip-trailing-cr -wp\"\n")
        self.assertEqual([u'diff', u'-r', u'-2..-1', u'--diff-options',
                          u'--strip-trailing-cr -wp'],
                          commands.get_alias("diff", config=my_config))

    def test_unicode(self):
        my_config = self._get_config("[ALIASES]\n"
            u"iam=whoami 'Erik B\u00e5gfors <erik@bagfors.nu>'\n")
        self.assertEqual([u'whoami', u'Erik B\u00e5gfors <erik@bagfors.nu>'],
                          commands.get_alias("iam", config=my_config))


class TestSeeAlso(tests.TestCase):
    """Tests for the see also functional of Command."""

    def test_default_subclass_no_see_also(self):
        class ACommand(commands.Command):
            """A sample command."""
        command = ACommand()
        self.assertEqual([], command.get_see_also())

    def test__see_also(self):
        """When _see_also is defined, it sets the result of get_see_also()."""
        class ACommand(commands.Command):
            _see_also = ['bar', 'foo']
        command = ACommand()
        self.assertEqual(['bar', 'foo'], command.get_see_also())

    def test_deduplication(self):
        """Duplicates in _see_also are stripped out."""
        class ACommand(commands.Command):
            _see_also = ['foo', 'foo']
        command = ACommand()
        self.assertEqual(['foo'], command.get_see_also())

    def test_sorted(self):
        """_see_also is sorted by get_see_also."""
        class ACommand(commands.Command):
            _see_also = ['foo', 'bar']
        command = ACommand()
        self.assertEqual(['bar', 'foo'], command.get_see_also())

    def test_additional_terms(self):
        """Additional terms can be supplied and are deduped and sorted."""
        class ACommand(commands.Command):
            _see_also = ['foo', 'bar']
        command = ACommand()
        self.assertEqual(['bar', 'foo', 'gam'],
            command.get_see_also(['gam', 'bar', 'gam']))


class TestRegisterLazy(tests.TestCase):

    def setUp(self):
        tests.TestCase.setUp(self)
        import bzrlib.tests.fake_command
        del sys.modules['bzrlib.tests.fake_command']
        global lazy_command_imported
        lazy_command_imported = False
        commands.install_bzr_command_hooks()

    @staticmethod
    def remove_fake():
        commands.plugin_cmds.remove('fake')

    def assertIsFakeCommand(self, cmd_obj):
        from bzrlib.tests.fake_command import cmd_fake
        self.assertIsInstance(cmd_obj, cmd_fake)

    def test_register_lazy(self):
        """Ensure lazy registration works"""
        commands.plugin_cmds.register_lazy('cmd_fake', [],
                                           'bzrlib.tests.fake_command')
        self.addCleanup(self.remove_fake)
        self.assertFalse(lazy_command_imported)
        fake_instance = commands.get_cmd_object('fake')
        self.assertTrue(lazy_command_imported)
        self.assertIsFakeCommand(fake_instance)

    def test_get_unrelated_does_not_import(self):
        commands.plugin_cmds.register_lazy('cmd_fake', [],
                                           'bzrlib.tests.fake_command')
        self.addCleanup(self.remove_fake)
        commands.get_cmd_object('status')
        self.assertFalse(lazy_command_imported)

    def test_aliases(self):
        commands.plugin_cmds.register_lazy('cmd_fake', ['fake_alias'],
                                           'bzrlib.tests.fake_command')
        self.addCleanup(self.remove_fake)
        fake_instance = commands.get_cmd_object('fake_alias')
        self.assertIsFakeCommand(fake_instance)


class TestExtendCommandHook(tests.TestCase):

    def test_fires_on_get_cmd_object(self):
        # The extend_command(cmd) hook fires when commands are delivered to the
        # ui, not simply at registration (because lazy registered plugin
        # commands are registered).
        # when they are simply created.
        hook_calls = []
        commands.install_bzr_command_hooks()
        commands.Command.hooks.install_named_hook(
            "extend_command", hook_calls.append, None)
        # create a command, should not fire
        class ACommand(commands.Command):
            """A sample command."""
        cmd = ACommand()
        self.assertEqual([], hook_calls)
        # -- as a builtin
        # register the command class, should not fire
        try:
            builtins.cmd_test_extend_command_hook = ACommand
            self.assertEqual([], hook_calls)
            # and ask for the object, should fire
            cmd = commands.get_cmd_object('test-extend-command-hook')
            # For resilience - to ensure all code paths hit it - we
            # fire on everything returned in the 'cmd_dict', which is currently
            # all known commands, so assert that cmd is in hook_calls
            self.assertSubset([cmd], hook_calls)
            del hook_calls[:]
        finally:
            del builtins.cmd_test_extend_command_hook
        # -- as a plugin lazy registration
        try:
            # register the command class, should not fire
            commands.plugin_cmds.register_lazy('cmd_fake', [],
                                               'bzrlib.tests.fake_command')
            self.assertEqual([], hook_calls)
            # and ask for the object, should fire
            cmd = commands.get_cmd_object('fake')
            self.assertEqual([cmd], hook_calls)
        finally:
            commands.plugin_cmds.remove('fake')


class TestGetCommandHook(tests.TestCase):

    def test_fires_on_get_cmd_object(self):
        # The get_command(cmd) hook fires when commands are delivered to the
        # ui.
        commands.install_bzr_command_hooks()
        hook_calls = []
        class ACommand(commands.Command):
            """A sample command."""
        def get_cmd(cmd_or_None, cmd_name):
            hook_calls.append(('called', cmd_or_None, cmd_name))
            if cmd_name in ('foo', 'info'):
                return ACommand()
        commands.Command.hooks.install_named_hook(
            "get_command", get_cmd, None)
        # create a command directly, should not fire
        cmd = ACommand()
        self.assertEqual([], hook_calls)
        # ask by name, should fire and give us our command
        cmd = commands.get_cmd_object('foo')
        self.assertEqual([('called', None, 'foo')], hook_calls)
        self.assertIsInstance(cmd, ACommand)
        del hook_calls[:]
        # ask by a name that is supplied by a builtin - the hook should still
        # fire and we still get our object, but we should see the builtin
        # passed to the hook.
        cmd = commands.get_cmd_object('info')
        self.assertIsInstance(cmd, ACommand)
        self.assertEqual(1, len(hook_calls))
        self.assertEqual('info', hook_calls[0][2])
        self.assertIsInstance(hook_calls[0][1], builtins.cmd_info)


class TestGetMissingCommandHook(tests.TestCase):

    def test_fires_on_get_cmd_object(self):
        # The get_missing_command(cmd) hook fires when commands are delivered to the
        # ui.
        hook_calls = []
        class ACommand(commands.Command):
            """A sample command."""
        def get_missing_cmd(cmd_name):
            hook_calls.append(('called', cmd_name))
            if cmd_name in ('foo', 'info'):
                return ACommand()
        commands.Command.hooks.install_named_hook(
            "get_missing_command", get_missing_cmd, None)
        # create a command directly, should not fire
        cmd = ACommand()
        self.assertEqual([], hook_calls)
        # ask by name, should fire and give us our command
        cmd = commands.get_cmd_object('foo')
        self.assertEqual([('called', 'foo')], hook_calls)
        self.assertIsInstance(cmd, ACommand)
        del hook_calls[:]
        # ask by a name that is supplied by a builtin - the hook should not
        # fire and we still get our object.
        commands.install_bzr_command_hooks()
        cmd = commands.get_cmd_object('info')
        self.assertNotEqual(None, cmd)
        self.assertEqual(0, len(hook_calls))


class TestListCommandHook(tests.TestCase):

    def test_fires_on_all_command_names(self):
        # The list_commands() hook fires when all_command_names() is invoked.
        hook_calls = []
        commands.install_bzr_command_hooks()
        def list_my_commands(cmd_names):
            hook_calls.append('called')
            cmd_names.update(['foo', 'bar'])
            return cmd_names
        commands.Command.hooks.install_named_hook(
            "list_commands", list_my_commands, None)
        # Get a command, which should not trigger the hook.
        cmd = commands.get_cmd_object('info')
        self.assertEqual([], hook_calls)
        # Get all command classes (for docs and shell completion).
        cmds = list(commands.all_command_names())
        self.assertEqual(['called'], hook_calls)
        self.assertSubset(['foo', 'bar'], cmds)
