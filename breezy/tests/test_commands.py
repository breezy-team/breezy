# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

import contextlib
import errno
import gc
import inspect
import os
import pickle
import sys
import weakref
from io import StringIO

import breezy

from .. import builtins, commands, config, errors, option, osutils, tests, trace, ui
from .. import help as _mod_help
from ..commands import display_command
from ..externalcommand import ExternalCommand
from . import TestSkipped


class TestCommands(tests.TestCase):
    def test_all_commands_have_help(self):
        commands._register_builtin_commands()
        commands_without_help = set()
        base_doc = inspect.getdoc(commands.Command)
        for cmd_name in commands.all_command_names():
            cmd = commands.get_cmd_object(cmd_name)
            cmd_help = cmd.help()
            if not cmd_help or cmd_help == base_doc:
                commands_without_help.append(cmd_name)
        self.assertLength(0, commands_without_help)

    def test_display_command(self):
        """EPIPE message is selectively suppressed."""

        def pipe_thrower():
            raise OSError(errno.EPIPE, "Bogus pipe error")

        self.assertRaises(IOError, pipe_thrower)

        @display_command
        def non_thrower():
            pipe_thrower()

        non_thrower()

        @display_command
        def other_thrower():
            raise OSError(errno.ESPIPE, "Bogus pipe error")

        self.assertRaises(IOError, other_thrower)

    def test_unicode_command(self):
        # This error is thrown when we can't find the command in the
        # list of available commands
        self.assertRaises(errors.CommandError, commands.run_bzr, ["cmd\xb5"])

    def test_unicode_option(self):
        # This error is actually thrown by optparse, when it
        # can't find the given option
        import optparse

        if optparse.__version__ == "1.5.3":
            raise TestSkipped("optparse 1.5.3 can't handle unicode options")
        self.assertRaises(
            errors.CommandError, commands.run_bzr, ["log", "--option\xb5"]
        )

    @staticmethod
    def get_command(options):
        class cmd_foo(commands.Command):
            __doc__ = "Bar"

            takes_options = options

        return cmd_foo()

    def test_help_hidden(self):
        c = self.get_command([option.Option("foo", hidden=True)])
        self.assertNotContainsRe(c.get_help_text(), "--foo")

    def test_help_not_hidden(self):
        c = self.get_command([option.Option("foo", hidden=False)])
        self.assertContainsRe(c.get_help_text(), "--foo")


class TestInsideCommand(tests.TestCaseInTempDir):
    def test_command_see_config_overrides(self):
        def run(cmd):
            # We override the run() command method so we can observe the
            # overrides from inside.
            c = config.GlobalStack()
            self.assertEqual("12", c.get("xx"))
            self.assertEqual("foo", c.get("yy"))

        self.overrideAttr(builtins.cmd_rocks, "run", run)
        self.run_bzr(["rocks", "-Oxx=12", "-Oyy=foo"])
        c = config.GlobalStack()
        # Ensure that we don't leak outside of the command
        self.assertEqual(None, c.get("xx"))
        self.assertEqual(None, c.get("yy"))


class TestInvokedAs(tests.TestCase):
    def test_invoked_as(self):
        """The command object knows the actual name used to invoke it."""
        commands.install_bzr_command_hooks()
        commands._register_builtin_commands()
        # get one from the real get_cmd_object.
        c = commands.get_cmd_object("ci")
        self.assertIsInstance(c, builtins.cmd_commit)
        self.assertEqual(c.invoked_as, "ci")


class TestGetAlias(tests.TestCase):
    def _get_config(self, config_text):
        my_config = config.GlobalConfig.from_string(config_text)
        return my_config

    def test_simple(self):
        my_config = self._get_config("[ALIASES]\ndiff=diff -r -2..-1\n")
        self.assertEqual(
            ["diff", "-r", "-2..-1"], commands.get_alias("diff", config=my_config)
        )

    def test_single_quotes(self):
        my_config = self._get_config(
            "[ALIASES]\ndiff=diff -r -2..-1 --diff-options '--strip-trailing-cr -wp'\n"
        )
        self.assertEqual(
            ["diff", "-r", "-2..-1", "--diff-options", "--strip-trailing-cr -wp"],
            commands.get_alias("diff", config=my_config),
        )

    def test_double_quotes(self):
        my_config = self._get_config(
            '[ALIASES]\ndiff=diff -r -2..-1 --diff-options "--strip-trailing-cr -wp"\n'
        )
        self.assertEqual(
            ["diff", "-r", "-2..-1", "--diff-options", "--strip-trailing-cr -wp"],
            commands.get_alias("diff", config=my_config),
        )

    def test_unicode(self):
        my_config = self._get_config(
            '[ALIASES]\niam=whoami "Erik B\u00e5gfors <erik@bagfors.nu>"\n'
        )
        self.assertEqual(
            ["whoami", "Erik B\u00e5gfors <erik@bagfors.nu>"],
            commands.get_alias("iam", config=my_config),
        )


class TestSeeAlso(tests.TestCase):
    """Tests for the see also functional of Command."""

    @staticmethod
    def _get_command_with_see_also(see_also):
        class ACommand(commands.Command):
            __doc__ = """A sample command."""
            _see_also = see_also

        return ACommand()

    def test_default_subclass_no_see_also(self):
        command = self._get_command_with_see_also([])
        self.assertEqual([], command.get_see_also())

    def test__see_also(self):
        """When _see_also is defined, it sets the result of get_see_also()."""
        command = self._get_command_with_see_also(["bar", "foo"])
        self.assertEqual(["bar", "foo"], command.get_see_also())

    def test_deduplication(self):
        """Duplicates in _see_also are stripped out."""
        command = self._get_command_with_see_also(["foo", "foo"])
        self.assertEqual(["foo"], command.get_see_also())

    def test_sorted(self):
        """_see_also is sorted by get_see_also."""
        command = self._get_command_with_see_also(["foo", "bar"])
        self.assertEqual(["bar", "foo"], command.get_see_also())

    def test_additional_terms(self):
        """Additional terms can be supplied and are deduped and sorted."""
        command = self._get_command_with_see_also(["foo", "bar"])
        self.assertEqual(
            ["bar", "foo", "gam"], command.get_see_also(["gam", "bar", "gam"])
        )


class TestRegisterLazy(tests.TestCase):
    def setUp(self):
        super().setUp()
        import breezy.tests.fake_command  # noqa: F401

        del sys.modules["breezy.tests.fake_command"]
        global lazy_command_imported
        lazy_command_imported = False
        commands.install_bzr_command_hooks()

    @staticmethod
    def remove_fake():
        commands.plugin_cmds.remove("fake")

    def assertIsFakeCommand(self, cmd_obj):
        from .fake_command import cmd_fake

        self.assertIsInstance(cmd_obj, cmd_fake)

    def test_register_lazy(self):
        """Ensure lazy registration works."""
        commands.plugin_cmds.register_lazy("cmd_fake", [], "breezy.tests.fake_command")
        self.addCleanup(self.remove_fake)
        self.assertFalse(lazy_command_imported)
        fake_instance = commands.get_cmd_object("fake")
        self.assertTrue(lazy_command_imported)
        self.assertIsFakeCommand(fake_instance)

    def test_get_unrelated_does_not_import(self):
        commands.plugin_cmds.register_lazy("cmd_fake", [], "breezy.tests.fake_command")
        self.addCleanup(self.remove_fake)
        commands.get_cmd_object("status")
        self.assertFalse(lazy_command_imported)

    def test_aliases(self):
        commands.plugin_cmds.register_lazy(
            "cmd_fake", ["fake_alias"], "breezy.tests.fake_command"
        )
        self.addCleanup(self.remove_fake)
        fake_instance = commands.get_cmd_object("fake_alias")
        self.assertIsFakeCommand(fake_instance)


class TestCommandRegistry(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.registry = commands.CommandRegistry()
        self.warnings = []
        self.overrideAttr(
            trace, "warning", lambda msg, *args: self.warnings.append(msg % args)
        )

    def make_command(self, name, aliases=()):
        return type(f"cmd_{name}", (commands.Command,), {"aliases": list(aliases)})

    def test_get_by_name_and_alias(self):
        cmd_foo_bar = self.make_command("foo_bar", ["fb"])
        self.assertIs(None, self.registry.register(cmd_foo_bar))
        self.assertIs(cmd_foo_bar, self.registry.get("foo-bar"))
        self.assertIs(cmd_foo_bar, self.registry.get("fb"))
        self.assertRaises(KeyError, self.registry.get, "nope")
        self.assertEqual(["foo-bar"], self.registry.keys())
        self.assertEqual(["fb"], self.registry.get_info("foo-bar").aliases)
        self.assertIs(None, self.registry.get_info("nope"))

    def test_duplicate_keeps_first(self):
        first = self.make_command("foo")
        second = self.make_command("foo", ["f"])
        self.registry.register(first)
        self.assertIs(first, self.registry.register(second))
        self.assertIs(first, self.registry.get("foo"))
        self.assertRaises(KeyError, self.registry.get, "f")
        self.assertEqual(
            [
                "Two plugins defined the same command: 'cmd_foo'",
                f"Not loading the one in {sys.modules[__name__]!r}",
                f"Previously this command was registered from {sys.modules[__name__]!r}",
            ],
            self.warnings,
        )

    def test_decorate_replaces(self):
        first = self.make_command("foo")
        second = self.make_command("foo")
        self.registry.register(first)
        self.assertIs(first, self.registry.register(second, decorate=True))
        self.assertIs(second, self.registry.get("foo"))
        self.assertEqual([], self.warnings)

    def test_previous_from_overridden_registry(self):
        builtin = commands.CommandRegistry()
        first = self.make_command("foo")
        builtin.register(first)
        self.registry.overridden_registry = builtin
        second = self.make_command("foo")
        self.assertIs(first, self.registry.register(second, decorate=True))

    def test_remove(self):
        self.registry.register(self.make_command("foo", ["f"]))
        self.registry.remove("foo")
        self.assertRaises(KeyError, self.registry.get, "foo")
        self.assertRaises(KeyError, self.registry.get, "f")
        self.assertRaises(KeyError, self.registry.remove, "foo")

    def test_register_lazy_duplicate(self):
        self.registry.register_lazy("cmd_fake", [], "breezy.tests.fake_command")
        self.assertRaises(
            KeyError,
            self.registry.register_lazy,
            "cmd_fake",
            [],
            "breezy.tests.fake_command",
        )

    def test_native_command_is_builtin(self):
        commands._register_builtin_commands()
        self.assertIs(
            builtins.cmd_rocks, commands.builtin_command_registry.get("rocks")
        )


class TestExtendCommandHook(tests.TestCase):
    def test_fires_on_get_cmd_object(self):
        # The extend_command(cmd) hook fires when commands are delivered to the
        # ui, not simply at registration (because lazy registered plugin
        # commands are registered).
        # when they are simply created.
        hook_calls = []
        commands.install_bzr_command_hooks()
        commands.Command.hooks.install_named_hook(
            "extend_command", hook_calls.append, None
        )
        # create a command, should not fire

        class cmd_test_extend_command_hook(commands.Command):
            __doc__ = """A sample command."""

        self.assertEqual([], hook_calls)
        # -- as a builtin
        # register the command class, should not fire
        try:
            commands.builtin_command_registry.register(cmd_test_extend_command_hook)
            self.assertEqual([], hook_calls)
            # and ask for the object, should fire
            cmd = commands.get_cmd_object("test-extend-command-hook")
            # For resilience - to ensure all code paths hit it - we
            # fire on everything returned in the 'cmd_dict', which is currently
            # all known commands, so assert that cmd is in hook_calls
            self.assertSubset([cmd], hook_calls)
            del hook_calls[:]
        finally:
            commands.builtin_command_registry.remove("test-extend-command-hook")
        # -- as a plugin lazy registration
        try:
            # register the command class, should not fire
            commands.plugin_cmds.register_lazy(
                "cmd_fake", [], "breezy.tests.fake_command"
            )
            self.assertEqual([], hook_calls)
            # and ask for the object, should fire
            cmd = commands.get_cmd_object("fake")
            self.assertEqual([cmd], hook_calls)
        finally:
            commands.plugin_cmds.remove("fake")


class TestGetCommandHook(tests.TestCase):
    def test_fires_on_get_cmd_object(self):
        # The get_command(cmd) hook fires when commands are delivered to the
        # ui.
        commands.install_bzr_command_hooks()
        hook_calls = []

        class ACommand(commands.Command):
            __doc__ = """A sample command."""

        def get_cmd(cmd_or_none, cmd_name):
            hook_calls.append(("called", cmd_or_none, cmd_name))
            if cmd_name in ("foo", "info"):
                return ACommand()

        commands.Command.hooks.install_named_hook("get_command", get_cmd, None)
        # create a command directly, should not fire
        cmd = ACommand()
        self.assertEqual([], hook_calls)
        # ask by name, should fire and give us our command
        cmd = commands.get_cmd_object("foo")
        self.assertEqual([("called", None, "foo")], hook_calls)
        self.assertIsInstance(cmd, ACommand)
        del hook_calls[:]
        # ask by a name that is supplied by a builtin - the hook should still
        # fire and we still get our object, but we should see the builtin
        # passed to the hook.
        cmd = commands.get_cmd_object("info")
        self.assertIsInstance(cmd, ACommand)
        self.assertEqual(1, len(hook_calls))
        self.assertEqual("info", hook_calls[0][2])
        self.assertIsInstance(hook_calls[0][1], builtins.cmd_info)


class TestCommandNotFound(tests.TestCase):
    def setUp(self):
        super().setUp()
        commands._register_builtin_commands()
        commands.install_bzr_command_hooks()

    def test_not_found_no_suggestion(self):
        e = self.assertRaises(
            errors.CommandError, commands.get_cmd_object, "idontexistand"
        )
        self.assertEqual('unknown command "idontexistand"', str(e))

    def test_not_found_with_suggestion(self):
        e = self.assertRaises(errors.CommandError, commands.get_cmd_object, "statue")
        self.assertEqual('unknown command "statue". Perhaps you meant "status"', str(e))


class TestGetMissingCommandHook(tests.TestCase):
    def hook_missing(self):
        """Hook get_missing_command for testing."""
        self.hook_calls = []

        class ACommand(commands.Command):
            __doc__ = """A sample command."""

        def get_missing_cmd(cmd_name):
            self.hook_calls.append(("called", cmd_name))
            if cmd_name in ("foo", "info"):
                return ACommand()

        commands.Command.hooks.install_named_hook(
            "get_missing_command", get_missing_cmd, None
        )
        self.ACommand = ACommand

    def test_fires_on_get_cmd_object(self):
        # The get_missing_command(cmd) hook fires when commands are delivered to the
        # ui.
        self.hook_missing()
        # create a command directly, should not fire
        self.cmd = self.ACommand()
        self.assertEqual([], self.hook_calls)
        # ask by name, should fire and give us our command
        cmd = commands.get_cmd_object("foo")
        self.assertEqual([("called", "foo")], self.hook_calls)
        self.assertIsInstance(cmd, self.ACommand)
        del self.hook_calls[:]
        # ask by a name that is supplied by a builtin - the hook should not
        # fire and we still get our object.
        commands.install_bzr_command_hooks()
        cmd = commands.get_cmd_object("info")
        self.assertNotEqual(None, cmd)
        self.assertEqual(0, len(self.hook_calls))

    def test_skipped_on_HelpCommandIndex_get_topics(self):
        # The get_missing_command(cmd_name) hook is not fired when
        # looking up help topics.
        self.hook_missing()
        topic = commands.HelpCommandIndex()
        topic.get_topics("foo")
        self.assertEqual([], self.hook_calls)


class TestListCommandHook(tests.TestCase):
    def test_fires_on_all_command_names(self):
        # The list_commands() hook fires when all_command_names() is invoked.
        hook_calls = []
        commands.install_bzr_command_hooks()

        def list_my_commands(cmd_names):
            hook_calls.append("called")
            cmd_names.update(["foo", "bar"])
            return cmd_names

        commands.Command.hooks.install_named_hook(
            "list_commands", list_my_commands, None
        )
        # Get a command, which should not trigger the hook.
        commands.get_cmd_object("info")
        self.assertEqual([], hook_calls)
        # Get all command classes (for docs and shell completion).
        cmds = list(commands.all_command_names())
        self.assertEqual(["called"], hook_calls)
        self.assertSubset(["foo", "bar"], cmds)

    def test_hook_returning_none(self):
        commands.install_bzr_command_hooks()

        def list_nothing(cmd_names):
            return None

        commands.Command.hooks.install_named_hook(
            "list_commands", list_nothing, "list nothing"
        )
        e = self.assertRaises(AssertionError, commands.all_command_names)
        self.assertEqual("hook list nothing returned None", str(e))


class TestPreAndPostCommandHooks(tests.TestCase):
    class TestError(Exception):
        __doc__ = """A test exception."""

    def test_pre_and_post_hooks(self):
        hook_calls = []

        def pre_command(cmd):
            self.assertEqual([], hook_calls)
            hook_calls.append("pre")

        def post_command(cmd):
            self.assertEqual(["pre", "run"], hook_calls)
            hook_calls.append("post")

        def run(cmd):
            self.assertEqual(["pre"], hook_calls)
            hook_calls.append("run")

        self.overrideAttr(builtins.cmd_rocks, "run", run)
        commands.install_bzr_command_hooks()
        commands.Command.hooks.install_named_hook("pre_command", pre_command, None)
        commands.Command.hooks.install_named_hook("post_command", post_command, None)

        self.assertEqual([], hook_calls)
        self.run_bzr(["rocks", "-Oxx=12", "-Oyy=foo"])
        self.assertEqual(["pre", "run", "post"], hook_calls)

    def test_post_hook_provided_exception(self):
        hook_calls = []

        def post_command(cmd):
            hook_calls.append("post")

        def run(cmd):
            hook_calls.append("run")
            raise self.TestError()

        self.overrideAttr(builtins.cmd_rocks, "run", run)
        commands.install_bzr_command_hooks()
        commands.Command.hooks.install_named_hook("post_command", post_command, None)

        self.assertEqual([], hook_calls)
        self.assertRaises(self.TestError, commands.run_bzr, ["rocks"])
        self.assertEqual(["run", "post"], hook_calls)

    def test_pre_command_error(self):
        """Ensure an CommandError in pre_command aborts the command."""
        hook_calls = []

        def pre_command(cmd):
            hook_calls.append("pre")
            raise errors.CommandError()

        def post_command(cmd, e):
            self.fail("post_command should not be called")

        def run(cmd):
            self.fail("command should not be called")

        self.overrideAttr(builtins.cmd_rocks, "run", run)
        commands.install_bzr_command_hooks()
        commands.Command.hooks.install_named_hook("pre_command", pre_command, None)
        commands.Command.hooks.install_named_hook("post_command", post_command, None)

        self.assertEqual([], hook_calls)
        self.assertRaises(errors.CommandError, commands.run_bzr, ["rocks"])
        self.assertEqual(["pre"], hook_calls)


class GuessCommandTests(tests.TestCase):
    def setUp(self):
        super().setUp()
        commands._register_builtin_commands()
        commands.install_bzr_command_hooks()

    def test_guess_override(self):
        self.assertEqual("ci", commands.guess_command("ic"))

    def test_guess(self):
        commands.get_cmd_object("status")
        self.assertEqual("status", commands.guess_command("statue"))

    def test_none(self):
        self.assertIs(None, commands.guess_command("nothingisevenclose"))


class TestHelpTextForAllCommands(tests.TestCase):
    """Every command can describe itself.

    Building the help text reads each Python command into the Rust command
    description, so this exercises that against the whole command set.
    """

    def test_all_commands(self):
        commands._register_builtin_commands()
        commands.install_bzr_command_hooks()
        for name in sorted(commands.all_command_names()):
            cmd = commands.get_cmd_object(name)
            text = cmd.get_help_text(plain=False)
            self.assertStartsWith(text, ":Purpose: ")


class TestCommandWithoutBaseInit(tests.TestCase):
    def test_help_text(self):
        # A command need not call Command.__init__ to describe itself.
        class cmd_demo(commands.Command):
            """Demo."""

            def __init__(self):
                pass

        self.assertStartsWith(cmd_demo().get_help_text(), "Purpose: Demo.")


class TestExternalCommandHelp(tests.TestCaseInTempDir):
    def test_help_text(self):
        from ..externalcommand import ExternalCommand

        self.build_tree_contents([("mytool", b"#!/bin/sh\necho 'Do things.'\n")])
        os.chmod("mytool", 0o755)  # noqa: S103
        cmd = ExternalCommand(os.path.abspath("mytool"))
        self.assertEqual(
            f":Purpose: external command from {os.path.abspath('mytool')}\n"
            ":Usage:   brz mytool\n"
            "\n"
            ":Options:\n"
            "  -h, --help     Show help message.\n"
            "  -q, --quiet    Only display errors and warnings.\n"
            "  --usage        Show usage message and options.\n"
            "  -v, --verbose  Display more information.\n"
            "\n"
            ":Description:\n"
            "  Do things.\n"
            "\n",
            cmd.get_help_text(plain=False),
        )


class TestCommandCollected(tests.TestCase):
    def test_command_is_collected(self):
        class cmd_demo(commands.Command):
            """Demo."""

            def run(self):
                pass

        cmd = cmd_demo()
        ref = weakref.ref(cmd)
        del cmd
        gc.collect()
        self.assertIs(None, ref())


class TestPickleClasses(tests.TestCase):
    def test_classes(self):
        for cls in [commands.Command, commands.CommandRegistry, commands.CommandInfo]:
            self.assertIs(cls, pickle.loads(pickle.dumps(cls)))  # noqa: S301


class TestRustCommandBase(tests.TestCase):
    """The Command base class, subclassed from Python.

    Covers naming, help, the ExitStack/hook lifecycle, isinstance and
    class-attribute override.
    """

    def setUp(self):
        super().setUp()
        commands.install_bzr_command_hooks()
        self.RustCommand = commands.Command

    def test_name_and_attributes(self):
        class cmd_demo(self.RustCommand):
            """Demo."""

            aliases = ["dm"]
            takes_args = ["path?"]

            def run(self, path=None):
                return 0

        c = cmd_demo()
        self.assertEqual("demo", c.name())
        self.assertEqual(["dm"], c.aliases)
        self.assertEqual(["path?"], c.takes_args)
        self.assertEqual("demo", c.get_help_topic())
        self.assertEqual("brz demo [PATH]", c._usage())
        self.assertIs(None, c.plugin_name())
        self.assertIsInstance(c, self.RustCommand)

    def test_help_is_none_without_docstring(self):
        class cmd_nodoc(self.RustCommand):
            def run(self):
                return 0

        self.assertIs(None, cmd_nodoc().help())

    def test_help_returns_docstring(self):
        class cmd_doc(self.RustCommand):
            """My summary."""

            def run(self):
                return 0

        self.assertEqual("My summary.", cmd_doc().help())

    def test_run_lifecycle_fires_hooks_and_cleanups(self):
        events = []

        class cmd_demo(self.RustCommand):
            """Demo."""

            def run(self):
                self.add_cleanup(lambda: events.append("cleanup"))
                events.append("run")
                return 0

        commands.Command.hooks.install_named_hook(
            "pre_command", lambda cmd: events.append("pre"), None
        )
        commands.Command.hooks.install_named_hook(
            "post_command", lambda cmd: events.append("post"), None
        )
        self.assertEqual(0, cmd_demo().run())
        self.assertEqual(["pre", "run", "cleanup", "post"], events)

    def test_run_error_still_fires_post(self):
        events = []

        class cmd_boom(self.RustCommand):
            """Boom."""

            def run(self):
                events.append("run")
                raise ValueError("boom")

        commands.Command.hooks.install_named_hook(
            "pre_command", lambda cmd: events.append("pre"), None
        )
        commands.Command.hooks.install_named_hook(
            "post_command", lambda cmd: events.append("post"), None
        )
        self.assertRaises(ValueError, cmd_boom().run)
        self.assertEqual(["pre", "run", "post"], events)

    def test_class_attribute_override_of_run(self):
        class cmd_demo(self.RustCommand):
            """Demo."""

            def run(self):
                return 1

        def run2(self):
            return 7

        cmd_demo.run = run2
        self.assertEqual(7, cmd_demo().run())

    def test_default_run_raises_not_implemented(self):
        class cmd_bare(self.RustCommand):
            """Bare."""

        self.assertRaises(NotImplementedError, cmd_bare().run)


class TestNativeCommands(tests.TestCase):
    """Commands implemented in Rust are ordinary Command subclasses."""

    def setUp(self):
        super().setUp()
        commands.install_bzr_command_hooks()

    def test_class_attributes(self):
        from .._cmd_rs.commands import NativeCommand

        cls = builtins.cmd_version
        self.assertTrue(issubclass(cls, NativeCommand))
        self.assertTrue(issubclass(cls, commands.Command))
        self.assertEqual("breezy.builtins", cls.__module__)
        self.assertEqual("Show version of brz.", cls.__doc__)
        self.assertEqual("replace", cls.encoding_type)
        self.assertEqual(["short"], [o.name for o in cls.takes_options])
        self.assertFalse(cls.hidden)
        self.assertTrue(builtins.cmd_rocks.hidden)

    def test_registered_as_builtin(self):
        self.assertIsInstance(commands.get_cmd_object("rocks"), builtins.cmd_rocks)

    def test_option_reaches_run(self):
        out = self.run_bzr(["version", "--short"])[0]
        self.assertEqual(f"{breezy.version_string}\n", out)

    def test_unexpected_keyword(self):
        cmd = builtins.cmd_rocks()
        e = self.assertRaises(TypeError, cmd.run, bogus=True)
        self.assertEqual(
            "command 'rocks' got an unexpected keyword argument 'bogus'", str(e)
        )

    def test_wrong_value_type(self):
        cmd = builtins.cmd_version()
        e = self.assertRaises(TypeError, cmd.run, short="yes")
        self.assertEqual(
            "command 'version' got an invalid value for 'short': Str(\"yes\")",
            str(e),
        )

    def test_plugin_decorates_native_command(self):
        calls = []

        class cmd_rocks(builtins.cmd_rocks):
            takes_options = [option.Option("loudly", help="Rock loudly.")]

            def run(self, loudly=False):
                calls.append(loudly)
                return super().run()

        commands.register_command(cmd_rocks, decorate=True)
        self.addCleanup(commands.plugin_cmds.remove, "rocks")
        out = self.run_bzr(["rocks", "--loudly"])[0]
        self.assertEqual("It sure does!\n", out)
        self.assertEqual([True], calls)


class TestMatchArgform(tests.TestCase):
    """Matching of command-line arguments against ``takes_args``."""

    def test_plain_required(self):
        self.assertEqual(
            {"a": "x", "b": "y"},
            commands._match_argform("cmd", ["a", "b"], ["x", "y"]),
        )

    def test_optional_present_and_absent(self):
        self.assertEqual({"a": "x"}, commands._match_argform("cmd", ["a?"], ["x"]))
        self.assertEqual({}, commands._match_argform("cmd", ["a?"], []))

    def test_star_empty_is_none(self):
        self.assertEqual(
            {"file_list": None}, commands._match_argform("cmd", ["file*"], [])
        )

    def test_star_collects_remaining(self):
        self.assertEqual(
            {"file_list": ["a", "b"]},
            commands._match_argform("cmd", ["file*"], ["a", "b"]),
        )

    def test_plus_collects_remaining(self):
        self.assertEqual(
            {"file_list": ["a"]},
            commands._match_argform("cmd", ["file+"], ["a"]),
        )

    def test_all_but_one(self):
        self.assertEqual(
            {"names_list": ["a", "b"], "tail": "c"},
            commands._match_argform("cmd", ["names$", "tail"], ["a", "b", "c"]),
        )

    def test_missing_required(self):
        e = self.assertRaises(
            errors.CommandError, commands._match_argform, "cmd", ["loc"], []
        )
        self.assertEqual("command 'cmd' requires argument LOC", str(e))

    def test_plus_needs_one(self):
        e = self.assertRaises(
            errors.CommandError, commands._match_argform, "cmd", ["file+"], []
        )
        self.assertEqual("command 'cmd' needs one or more FILE", str(e))

    def test_extra_argument(self):
        e = self.assertRaises(
            errors.CommandError, commands._match_argform, "cmd", ["a"], ["x", "y"]
        )
        self.assertEqual("extra argument to command cmd: y", str(e))


class TestUsage(tests.TestCase):
    """The usage line built from ``takes_args``."""

    def _usage(self, takes_args):
        class cmd_sample(commands.Command):
            __doc__ = """Sample."""

        cmd = cmd_sample()
        cmd.takes_args = takes_args
        return cmd._usage()

    def test_no_args(self):
        self.assertEqual("brz sample", self._usage([]))

    def test_each_specifier(self):
        self.assertEqual("brz sample LOC", self._usage(["loc"]))
        self.assertEqual("brz sample [LOC]", self._usage(["loc?"]))
        self.assertEqual("brz sample [FILE...]", self._usage(["file*"]))
        self.assertEqual("brz sample FILE...", self._usage(["file+"]))
        self.assertEqual("brz sample NAMES...", self._usage(["names$"]))

    def test_multiple_args(self):
        self.assertEqual(
            "brz sample FROM [TO] [FILE...]",
            self._usage(["from", "to?", "file*"]),
        )


class TestGetHelpParts(tests.TestCase):
    """Splitting a command docstring into summary and sections."""

    def test_summary_only(self):
        summary, sections, order = commands.Command._get_help_parts("One line.")
        self.assertEqual("One line.", summary)
        self.assertEqual({}, sections)
        self.assertEqual([], order)

    def test_default_section(self):
        summary, sections, order = commands.Command._get_help_parts(
            "Summary.\n\nMore detail.\nSecond line."
        )
        self.assertEqual("Summary.", summary)
        self.assertEqual({None: "More detail.\nSecond line."}, sections)
        self.assertEqual([None], order)

    def test_named_sections_in_order(self):
        text = "Summary.\n\nBody.\n\n:Examples:\n  thing\n\n:See also: status"
        summary, sections, order = commands.Command._get_help_parts(text)
        self.assertEqual("Summary.", summary)
        # ":See also: status" is not a heading, so it stays in the default
        # section.
        self.assertEqual(
            {None: "Body.\n\n:See also: status", "Examples": "  thing\n"},
            sections,
        )
        self.assertEqual([None, "Examples"], order)

    def test_repeated_label_merges(self):
        text = "Summary.\n\n:Note:\n  first\n\n:Note:\n  second"
        _summary, sections, order = commands.Command._get_help_parts(text)
        self.assertEqual({"Note": "  first\n\n  second"}, sections)
        self.assertEqual(["Note"], order)


class TestPluginProvider(tests.TestCase):
    """The plugin-provider probe behind the get_missing_command hook."""

    def _register(self, key, provider):
        commands.command_providers_registry.register(key, provider)
        self.addCleanup(commands.command_providers_registry.remove, key)

    def _declining_provider(self):
        class Declines(commands.Provider):
            def plugin_for_command(self, cmd_name):
                raise commands.NoPluginAvailable(cmd_name)

        return Declines()

    def _supplying_provider(self):
        class Supplies(commands.Provider):
            def plugin_for_command(self, cmd_name):
                return {"name": "bzr-thing", "url": "http://example.com/thing"}

        return Supplies()

    def test_probe_without_providers(self):
        self.assertRaises(
            commands.NoPluginAvailable, commands.probe_for_provider, "thing"
        )

    def test_probe_skips_declining_provider(self):
        self._register("declines", self._declining_provider())
        supplier = self._supplying_provider()
        self._register("supplies", supplier)
        metadata, provider = commands.probe_for_provider("thing")
        self.assertEqual(
            {"name": "bzr-thing", "url": "http://example.com/thing"}, metadata
        )
        self.assertIs(supplier, provider)

    def test_try_plugin_provider_reports_plugin(self):
        self._register("supplies", self._supplying_provider())
        e = self.assertRaises(
            commands.CommandAvailableInPlugin, commands._try_plugin_provider, "thing"
        )
        self.assertEqual("thing", e.cmd_name)
        self.assertEqual(
            '"thing" is not a standard brz command. \n'
            "However, the following official plugin provides this command: bzr-thing\n"
            "You can install it by going to: http://example.com/thing",
            str(e),
        )

    def test_try_plugin_provider_silent_when_unavailable(self):
        self._register("declines", self._declining_provider())
        self.assertIs(None, commands._try_plugin_provider("thing"))


class TestExternalCommandLookup(tests.TestCaseInTempDir):
    """The BZRPATH search behind the external-command get_command hook."""

    def _make_command(self, name):
        self.build_tree_contents([(name, b"#!/bin/sh\n")])
        return osutils.abspath(name)

    def test_found_on_bzrpath(self):
        path = self._make_command("my-ext-cmd")
        self.overrideEnv("BZRPATH", self.test_dir)
        cmd = ExternalCommand.find_command("my-ext-cmd")
        self.assertEqual(path, cmd.path)
        self.assertEqual("my-ext-cmd", cmd.name())

    def test_empty_entries_skipped(self):
        path = self._make_command("my-ext-cmd")
        self.overrideEnv("BZRPATH", os.pathsep + self.test_dir)
        self.assertEqual(path, ExternalCommand.find_command("my-ext-cmd").path)

    def test_not_found(self):
        self.overrideEnv("BZRPATH", self.test_dir)
        self.assertIs(None, ExternalCommand.find_command("no-such-ext-cmd"))

    def test_unset_bzrpath(self):
        self.overrideEnv("BZRPATH", None)
        self.assertIs(None, ExternalCommand.find_command("my-ext-cmd"))

    def test_hook_keeps_command_found_so_far(self):
        self.overrideEnv("BZRPATH", self.test_dir)
        self.assertEqual(
            "already", commands._get_external_command("already", "my-ext-cmd")
        )

    def test_hook_returns_none_when_missing(self):
        self.overrideEnv("BZRPATH", self.test_dir)
        self.assertIs(None, commands._get_external_command(None, "no-such-ext-cmd"))


class TestCommandAccessorErrors(tests.TestCase):
    """Exceptions from a command's own accessors reach the caller.

    The Rust command trait answers these by calling into Python, so a raising
    accessor has to propagate rather than abort or be swallowed.
    """

    def setUp(self):
        super().setUp()
        commands.install_bzr_command_hooks()

    def _register(self, cmd_class):
        commands.register_command(cmd_class)
        self.addCleanup(commands.plugin_cmds.remove, cmd_class.__name__[4:])

    def test_help_error_propagates(self):
        class cmd_raisinghelp(commands.Command):
            __doc__ = "probe"

            def help(self):
                raise RuntimeError("boom from help")

        self._register(cmd_raisinghelp)
        e = self.assertRaises(
            RuntimeError, _mod_help.help, "raisinghelp", outfile=StringIO()
        )
        self.assertEqual("boom from help", str(e))

    def test_plugin_name_error_propagates(self):
        class cmd_raisingplugin(commands.Command):
            __doc__ = "probe"

            def plugin_name(self):
                raise ValueError("boom from plugin_name")

        self._register(cmd_raisingplugin)
        self.assertRaises(
            ValueError, _mod_help.help, "raisingplugin", outfile=StringIO()
        )

    def test_missing_topic_is_still_not_found(self):
        self.assertRaises(
            _mod_help.NoHelpTopic,
            _mod_help.help,
            "nosuchhelptopicatall",
            outfile=StringIO(),
        )


class TestExternalCommandRun(tests.TestCaseInTempDir):
    """Running an external command and capturing its help."""

    def _script(self, name, body):
        self.build_tree_contents([(name, body.encode())])
        os.chmod(name, 0o755)  # noqa: S103
        return ExternalCommand(osutils.abspath(name))

    def test_exit_code_returned(self):
        cmd = self._script("ok-cmd", "#!/bin/sh\nexit 0\n")
        self.assertEqual(0, cmd.run_argv_aliases([]))

    def test_nonzero_exit_code_returned(self):
        cmd = self._script("fail-cmd", "#!/bin/sh\nexit 7\n")
        self.assertEqual(7, cmd.run_argv_aliases([]))

    def test_signal_reported_as_negative(self):
        cmd = self._script("sig-cmd", "#!/bin/sh\nkill -TERM $$\n")
        self.assertEqual(-15, cmd.run_argv_aliases([]))

    def test_arguments_passed_through(self):
        cmd = self._script("echo-cmd", '#!/bin/sh\ntest "$1" = one || exit 9\n')
        self.assertEqual(0, cmd.run_argv_aliases(["one"]))

    def test_help_captures_output_despite_exit_code(self):
        cmd = self._script("help-cmd", "#!/bin/sh\necho 'Usage: x'\nexit 1\n")
        self.assertEqual(f"external command from {cmd.path}\n\nUsage: x\n", cmd.help())


class TestCommandCleanup(tests.TestCase):
    """The cleanup run after a command body.

    Both steps, logging the transport activity and resetting the verbosity,
    run whether the body returned or raised, and neither may discard the
    command's own error.
    """

    def setUp(self):
        super().setUp()
        commands.install_bzr_command_hooks()

    def _command(self, run):
        return type("cmd_cleanup_probe", (commands.Command,), {"run": run})()

    def _break_cleanup(self):
        def boom(**kwargs):
            raise RuntimeError("cleanup blew up")

        self.overrideAttr(ui.ui_factory, "log_transport_activity", boom)

    def test_verbosity_reset_after_success(self):
        self._command(lambda cmd: 0).run_argv_aliases([])
        self.assertEqual(0, trace.get_verbosity_level())

    def test_verbosity_reset_after_failure(self):
        def run(cmd, verbose=False):
            raise ValueError("boom")

        cmd = self._command(run)
        cmd.takes_options = ["verbose"]
        self.assertRaises(ValueError, cmd.run_argv_aliases, ["-v"])
        self.assertEqual(0, trace.get_verbosity_level())

    def test_failing_cleanup_keeps_the_command_error(self):
        def run(cmd, verbose=False):
            raise ValueError("the real error")

        self._break_cleanup()
        cmd = self._command(run)
        cmd.takes_options = ["verbose"]
        e = self.assertRaises(ValueError, cmd.run_argv_aliases, ["-v"])
        self.assertEqual("the real error", str(e))
        # The reset still happened, so the next command starts clean.
        self.assertEqual(0, trace.get_verbosity_level())

    def test_failing_cleanup_surfaces_when_the_command_succeeded(self):
        self._break_cleanup()
        self.assertRaises(
            RuntimeError, self._command(lambda cmd: 0).run_argv_aliases, []
        )
        self.assertEqual(0, trace.get_verbosity_level())


class TestRunBzrCatchErrors(tests.TestCase):
    def test_error_becomes_exit_code(self):
        self.assertEqual(3, commands.run_bzr_catch_errors(["no-such-command"]))

    def test_success(self):
        self.assertEqual(0, commands.run_bzr_catch_errors(["rocks"]))


class TestRunBzrCleanup(tests.TestCase):
    """The cleanup run_bzr does after a command."""

    def setUp(self):
        super().setUp()
        commands.install_bzr_command_hooks()

    def register(self, run):
        cmd_class = type("cmd_cleanup_probe", (commands.Command,), {"run": run})
        commands.register_command(cmd_class)
        self.addCleanup(commands.plugin_cmds.remove, "cleanup-probe")

    def break_reset(self):
        # The overrides are reset before the command too; only the reset after
        # it fails.
        overrides = breezy.get_global_state().cmdline_overrides
        calls = []
        reset = overrides._reset

        def boom():
            calls.append(None)
            if len(calls) > 1:
                raise RuntimeError("reset blew up")
            reset()

        self.overrideAttr(overrides, "_reset", boom)

    def test_failing_reset_surfaces(self):
        self.register(lambda cmd: 0)
        self.break_reset()
        self.assertRaises(RuntimeError, commands.run_bzr, ["cleanup-probe"])

    def test_failing_reset_keeps_the_command_error(self):
        def run(cmd):
            raise ValueError("the real error")

        self.register(run)
        self.break_reset()
        e = self.assertRaises(ValueError, commands.run_bzr, ["cleanup-probe"])
        self.assertEqual("the real error", str(e))

    def test_verbosity_restored(self):
        option.set_verbosity_level(2)
        self.addCleanup(option.set_verbosity_level, 0)
        self.register(lambda cmd: 0)
        commands.run_bzr(["cleanup-probe", "-v"])
        self.assertEqual(2, option.verbosity_level())


class TestCommandExitStack(tests.TestCase):
    """The ExitStack a command's run is wrapped in."""

    def _run(self, run):
        cmd_class = type("cmd_exit_stack_test", (commands.Command,), {"run": run})
        return cmd_class().run()

    def test_cleanups_run_in_reverse(self):
        log = []

        def run(cmd):
            cmd.add_cleanup(log.append, "first")
            cmd.add_cleanup(log.append, "second")
            log.append("body")
            return 7

        self.assertEqual(7, self._run(run))
        self.assertEqual(["body", "second", "first"], log)

    def test_cleanups_run_when_run_raises(self):
        log = []

        def run(cmd):
            cmd.add_cleanup(log.append, "cleanup")
            raise ValueError("boom")

        e = self.assertRaises(ValueError, self._run, run)
        self.assertEqual("boom", str(e))
        self.assertEqual(["cleanup"], log)

    def test_entered_context_can_suppress(self):
        log = []

        def run(cmd):
            cmd.enter_context(contextlib.suppress(ValueError))
            log.append("body")
            raise ValueError("swallowed")

        self.assertIs(None, self._run(run))
        self.assertEqual(["body"], log)

    def test_cleanup_now_runs_cleanups_early(self):
        log = []

        def run(cmd):
            cmd.add_cleanup(log.append, "early")
            cmd.cleanup_now()
            log.append("after")

        self._run(run)
        self.assertEqual(["early", "after"], log)
