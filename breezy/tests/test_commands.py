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

import errno
import inspect
import sys

from .. import builtins, commands, config, errors, option, tests
from ..commands import display_command
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


class TestRustPyCommand(tests.TestCase):
    """The Rust Command trait, exercised through the PyCommand wrapper.

    The wrapper implements the Rust Command trait by delegating to a Python
    command object. These tests assert the delegation round-trips for the
    grandfathered Python builtins.
    """

    def setUp(self):
        super().setUp()
        commands._register_builtin_commands()
        commands.install_bzr_command_hooks()
        from breezy._cmd_rs.commands import PyCommand

        self.PyCommand = PyCommand

    def test_simple_command(self):
        wrapped = self.PyCommand(commands.get_cmd_object("rocks"))
        self.assertEqual("rocks", wrapped.name())
        self.assertEqual([], wrapped.aliases())
        self.assertEqual([], wrapped.takes_args())
        self.assertEqual(True, wrapped.hidden())
        self.assertEqual("strict", wrapped.encoding_type())
        self.assertEqual("rocks", wrapped.invoked_as())
        self.assertIs(None, wrapped.plugin_name())
        self.assertEqual("Statement of optimism.", wrapped.help())

    def test_command_with_aliases_and_args(self):
        wrapped = self.PyCommand(commands.get_cmd_object("status"))
        self.assertEqual("status", wrapped.name())
        self.assertEqual(["st", "stat"], wrapped.aliases())
        self.assertEqual(["file*"], wrapped.takes_args())
        self.assertEqual(False, wrapped.hidden())
        self.assertEqual("replace", wrapped.encoding_type())

    def test_invoked_as_tracks_alias(self):
        wrapped = self.PyCommand(commands.get_cmd_object("ci"))
        self.assertEqual("commit", wrapped.name())
        self.assertEqual("ci", wrapped.invoked_as())

    def test_external_command(self):
        from ..externalcommand import ExternalCommand

        cmd = ExternalCommand("/usr/bin/some-external-tool")
        wrapped = self.PyCommand(cmd)
        # ExternalCommand overrides name() and bypasses Command.__init__.
        self.assertEqual("some-external-tool", wrapped.name())
        self.assertEqual([], wrapped.aliases())
        self.assertEqual([], wrapped.takes_args())
        self.assertEqual(False, wrapped.hidden())
        self.assertEqual("strict", wrapped.encoding_type())
        self.assertIs(None, wrapped.invoked_as())

    def test_all_commands_round_trip(self):
        # Wrap every resolvable command and assert each trait method agrees
        # with the underlying Python object, exercising PyCommand against the
        # whole command set.
        for name in sorted(commands.all_command_names()):
            cmd = commands.get_cmd_object(name)
            wrapped = self.PyCommand(cmd)
            self.assertEqual(cmd.name(), wrapped.name())
            self.assertEqual(list(cmd.aliases), wrapped.aliases())
            self.assertEqual(list(cmd.takes_args), wrapped.takes_args())
            self.assertEqual(cmd.hidden, wrapped.hidden())
            self.assertEqual(cmd.encoding_type, wrapped.encoding_type())
            self.assertEqual(cmd.invoked_as, wrapped.invoked_as())
            self.assertEqual(cmd.plugin_name(), wrapped.plugin_name())
            self.assertEqual(cmd.help(), wrapped.help())

    def test_get_cmd_object_runs_trait_check(self):
        # With the command_trait debug flag set, _get_cmd_object runs the
        # round-trip check itself for every lookup.
        from breezy import debug

        debug.set_debug_flag("command_trait")
        for name in sorted(commands.all_command_names()):
            commands.get_cmd_object(name)


class TestMatchArgform(tests.TestCase):
    """The Rust port of ``_match_argform``, reached through commands.py."""

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
    """The Rust port of ``Command._usage``."""

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
    """The Rust port of ``Command._get_help_parts``."""

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


class TestScanMasterOptions(tests.TestCase):
    """The Rust port of the run_bzr master-option scanner."""

    def _scan(self, argv):
        return commands._commands_rs.scan_master_options(argv)

    def test_no_master_options(self):
        opts, rest = self._scan(["status", "-v"])
        self.assertEqual(["status", "-v"], rest)
        self.assertFalse(opts.no_plugins)
        self.assertFalse(opts.builtin)

    def test_boolean_flags(self):
        opts, rest = self._scan(
            ["--no-plugins", "--builtin", "--no-aliases", "--no-l10n", "st"]
        )
        self.assertTrue(opts.no_plugins)
        self.assertTrue(opts.builtin)
        self.assertTrue(opts.no_aliases)
        self.assertTrue(opts.no_l10n)
        self.assertEqual(["st"], rest)

    def test_lsprof_file_consumes_next(self):
        opts, rest = self._scan(["--lsprof-file", "out.prof", "log"])
        self.assertTrue(opts.lsprof)
        self.assertEqual("out.prof", opts.lsprof_file)
        self.assertEqual(["log"], rest)

    def test_concurrency_consumes_next(self):
        opts, rest = self._scan(["--concurrency", "4", "selftest"])
        self.assertEqual("4", opts.concurrency)
        self.assertEqual(["selftest"], rest)

    def test_debug_and_override_collected(self):
        opts, rest = self._scan(["-Dhpss", "-Ofoo=bar", "-Dbytes", "log"])
        self.assertEqual(["hpss", "bytes"], opts.debug_flags)
        self.assertEqual(["foo=bar"], opts.config_overrides)
        self.assertEqual(["log"], rest)

    def test_profile_imports_dropped(self):
        _opts, rest = self._scan(["--profile-imports", "version"])
        self.assertEqual(["version"], rest)

    def test_missing_lookahead_raises(self):
        self.assertRaises(IndexError, self._scan, ["--lsprof-file"])
        self.assertRaises(IndexError, self._scan, ["--concurrency"])
