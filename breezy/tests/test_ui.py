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

"""Tests for the breezy ui."""

import time

from testtools.matchers import *

from .. import config, tests
from .. import ui as _mod_ui
from ..bzr import remote
from ..ui import text as _mod_ui_text
from . import fixtures, ui_testing
from .testui import ProgressRecordingUIFactory


class TestUIConfiguration(tests.TestCaseInTempDir):
    def test_output_encoding_configuration(self):
        enc = next(fixtures.generate_unicode_encodings())
        config.GlobalStack().set("output_encoding", enc)
        IO = ui_testing.BytesIOWithEncoding
        ui = _mod_ui.make_ui_for_terminal(IO(), IO(), IO())
        output = ui.make_output_stream()
        self.assertEqual(output.encoding, enc)


class TestTextUIFactory(tests.TestCase):
    def test_text_factory_confirm(self):
        # turns into reading a regular boolean
        with ui_testing.TestUIFactory("n\n") as ui:
            self.assertEqual(
                False,
                ui.confirm_action(
                    "Should %(thing)s pass?",
                    "breezy.tests.test_ui.confirmation",
                    {"thing": "this"},
                ),
            )

    def test_text_factory_ascii_password(self):
        ui = ui_testing.TestUIFactory("secret\n")
        with ui.nested_progress_bar():
            self.assertEqual(
                "secret",
                self.apply_redirected(ui.stdin, ui.stdout, ui.stderr, ui.get_password),
            )
            # ': ' is appended to prompt
            self.assertEqual(": ", ui.stderr.getvalue())
            self.assertEqual("", ui.stdout.readline())
            # stdin should be empty
            self.assertEqual("", ui.stdin.readline())

    def test_text_factory_unicode_password(self):
        """Test a unicode password."""
        ui = ui_testing.TextUIFactory("baz\u1234")
        password = ui.get_password("Hello \u1234 %(user)s", user="some\u1234")
        self.assertEqual("baz\u1234", password)
        self.assertEqual("Hello \u1234 some\u1234: ", ui.stderr.getvalue())
        # stdin and stdout should be empty
        self.assertEqual("", ui.stdin.readline())
        self.assertEqual("", ui.stdout.getvalue())

    def test_text_ui_get_boolean(self):
        stdin_text = (
            "y\n"  # True
            "n\n"  # False
            " \n y \n"  # True
            " no \n"  # False
            "yes with garbage\nY\n"  # True
            "not an answer\nno\n"  # False
            "I'm sure!\nyes\n"  # True
            "NO\n"  # False
            "foo\n"
        )
        with ui_testing.TextUIFactory(stdin_text) as factory:
            self.assertEqual(True, factory.get_boolean(""))
            self.assertEqual(False, factory.get_boolean(""))
            self.assertEqual(True, factory.get_boolean(""))
            self.assertEqual(False, factory.get_boolean(""))
            self.assertEqual(True, factory.get_boolean(""))
            self.assertEqual(False, factory.get_boolean(""))
            self.assertEqual(True, factory.get_boolean(""))
            self.assertEqual(False, factory.get_boolean(""))
            self.assertEqual("foo\n", factory.stdin.read())
            # stdin should be empty
            self.assertEqual("", factory.stdin.readline())
            # return false on EOF
            self.assertEqual(False, factory.get_boolean(""))

    def test_text_ui_choose_bad_parameters(self):
        with ui_testing.TextUIFactory("") as factory:
            # invalid default index
            self.assertRaises(ValueError, factory.choose, "", "&Yes\n&No", 3)
            # duplicated choice
            self.assertRaises(ValueError, factory.choose, "", "&choice\n&ChOiCe")
            # duplicated shortcut
            self.assertRaises(ValueError, factory.choose, "", "&choice1\nchoi&ce2")

    def test_text_ui_choose_prompt_explicit(self):
        # choices with explicit shortcuts
        with ui_testing.TextUIFactory("") as factory:
            factory.choose("prompt", "&yes\n&No\nmore &info")
            self.assertEqual(
                "prompt ([y]es, [N]o, more [i]nfo): \n", factory.stderr.getvalue()
            )

    def test_text_ui_choose_prompt_automatic(self):
        # automatic shortcuts
        with ui_testing.TextUIFactory("") as factory:
            factory.choose("prompt", "yes\nNo\nmore info")
            self.assertEqual(
                "prompt ([y]es, [N]o, [m]ore info): \n", factory.stderr.getvalue()
            )

    def test_text_ui_choose_return_values(self):
        def choose():
            return factory.choose("", "&Yes\n&No\nMaybe\nmore &info", 3)

        stdin_text = (
            "y\n"  # 0
            "n\n"  # 1
            " \n"  # default: 3
            " no \n"  # 1
            "b\na\nd \n"  # bad shortcuts, all ignored
            "yes with garbage\nY\n"  # 0
            "not an answer\nno\n"  # 1
            "info\nmore info\n"  # 3
            "Maybe\n"  # 2
            "foo\n"
        )
        with ui_testing.TextUIFactory(stdin_text) as factory:
            self.assertEqual(0, choose())
            self.assertEqual(1, choose())
            self.assertEqual(3, choose())
            self.assertEqual(1, choose())
            self.assertEqual(0, choose())
            self.assertEqual(1, choose())
            self.assertEqual(3, choose())
            self.assertEqual(2, choose())
            self.assertEqual("foo\n", factory.stdin.read())
            # stdin should be empty
            self.assertEqual("", factory.stdin.readline())
            # return None on EOF
            self.assertEqual(None, choose())

    def test_text_ui_choose_no_default(self):
        stdin_text = (
            " \n"  # no default, invalid!
            " yes \n"  # 0
            "foo\n"
        )
        with ui_testing.TextUIFactory(stdin_text) as factory:
            self.assertEqual(0, factory.choose("", "&Yes\n&No"))
            self.assertEqual("foo\n", factory.stdin.read())

    def test_text_ui_get_integer(self):
        stdin_text = "1\n  -2  \nhmmm\nwhat else ?\nCome on\nok 42\n4.24\n42\n"
        with ui_testing.TextUIFactory(stdin_text) as factory:
            self.assertEqual(1, factory.get_integer(""))
            self.assertEqual(-2, factory.get_integer(""))
            self.assertEqual(42, factory.get_integer(""))

    def test_text_factory_prompt(self):
        # see <https://launchpad.net/bugs/365891>
        with ui_testing.TextUIFactory() as factory:
            factory.prompt("foo %2e")
            self.assertEqual("", factory.stdout.getvalue())
            self.assertEqual("foo %2e", factory.stderr.getvalue())

    def test_text_factory_prompts_and_clears(self):
        # a get_boolean call should clear the pb before prompting
        out = ui_testing.StringIOAsTTY()
        self.overrideEnv("TERM", "xterm")
        factory = ui_testing.TextUIFactory("yada\ny\n", stdout=out, stderr=out)
        with factory:
            pb = factory.nested_progress_bar()
            pb._avail_width = lambda: 79
            pb.show_bar = False
            pb.show_spinner = False
            pb.show_count = False
            pb.update("foo", 0, 1)
            self.assertEqual(
                True,
                self.apply_redirected(
                    None,
                    factory.stdout,
                    factory.stdout,
                    factory.get_boolean,
                    "what do you want",
                ),
            )
            output = out.getvalue()
            self.assertContainsRe(output, "| foo *\r\r  *\r*")
            self.assertContainsString(
                output,
                r"what do you want? ([y]es, [n]o): what do you want? "
                r"([y]es, [n]o): ",
            )
            # stdin should have been totally consumed
            self.assertEqual("", factory.stdin.readline())

    def test_text_tick_after_update(self):
        ui_factory = ui_testing.TextUIFactory()
        with ui_factory.nested_progress_bar() as pb:
            pb.update("task", 0, 3)
            # Reset the clock, so that it actually tries to repaint itself
            ui_factory._progress_view._last_repaint = time.time() - 1.0
            pb.tick()

    def test_text_ui_getusername(self):
        ui = ui_testing.TextUIFactory("someuser\n\n")
        self.assertEqual("someuser", ui.get_username("Hello %(host)s", host="some"))
        self.assertEqual("Hello some: ", ui.stderr.getvalue())
        self.assertEqual("", ui.stdout.getvalue())
        self.assertEqual("", ui.get_username("Gebruiker"))
        # stdin should be empty
        self.assertEqual("", ui.stdin.readline())

    def test_text_ui_getusername_unicode(self):
        ui = ui_testing.TextUIFactory("someuser\u1234")
        username = ui.get_username("Hello %(host)s", host="some\u1234")
        self.assertEqual("someuser\u1234", username)
        self.assertEqual("Hello some\u1234: ", ui.stderr.getvalue())
        self.assertEqual("", ui.stdout.getvalue())

    def test_quietness(self):
        self.overrideEnv("BRZ_PROGRESS_BAR", "text")
        ui_factory = ui_testing.TextUIFactory(stderr=ui_testing.StringIOAsTTY())
        with ui_factory:
            self.assertIsInstance(
                ui_factory._progress_view, _mod_ui_text.TextProgressView
            )
            ui_factory.be_quiet(True)
            self.assertIsInstance(
                ui_factory._progress_view, _mod_ui_text.NullProgressView
            )

    def test_text_ui_show_user_warning(self):
        from ..bzr.groupcompress_repo import RepositoryFormat2a
        from ..bzr.knitpack_repo import RepositoryFormatKnitPack5

        ui = ui_testing.TextUIFactory()
        remote_fmt = remote.RemoteRepositoryFormat()
        remote_fmt._network_name = RepositoryFormatKnitPack5().network_name()
        ui.show_user_warning(
            "cross_format_fetch", from_format=RepositoryFormat2a(), to_format=remote_fmt
        )
        self.assertEqual("", ui.stdout.getvalue())
        self.assertContainsRe(
            ui.stderr.getvalue(),
            "^Doing on-the-fly conversion from RepositoryFormat2a\\(\\) to "
            "RemoteRepositoryFormat\\(_network_name="
            "b?'Bazaar RepositoryFormatKnitPack5 \\(bzr 1.6\\)\\\\n'\\)\\.\n"
            "This may take some time. Upgrade the repositories to "
            "the same format for better performance\\.\n$",
        )
        # and now with it suppressed please
        ui = ui_testing.TextUIFactory()
        ui.suppressed_warnings.add("cross_format_fetch")
        ui.show_user_warning(
            "cross_format_fetch", from_format=RepositoryFormat2a(), to_format=remote_fmt
        )
        self.assertEqual("", ui.stdout.getvalue())
        self.assertEqual("", ui.stderr.getvalue())


class TestTextUIOutputStream(tests.TestCase):
    """Tests for output stream that synchronizes with progress bar."""

    def test_output_clears_terminal(self):
        clear_calls = []

        uif = ui_testing.TextUIFactory()
        uif.clear_term = lambda: clear_calls.append("clear")

        stream = _mod_ui_text.TextUIOutputStream(uif, uif.stdout, "utf-8", "strict")
        stream.write("Hello world!\n")
        stream.write("there's more...\n")
        stream.writelines(["1\n", "2\n", "3\n"])

        self.assertEqual(
            uif.stdout.getvalue(), "Hello world!\nthere's more...\n1\n2\n3\n"
        )
        self.assertEqual(["clear", "clear", "clear"], clear_calls)

        stream.flush()


class UITests(tests.TestCase):
    def test_progress_construction(self):
        """TextUIFactory constructs the right progress view."""
        FileStringIO = ui_testing.StringIOWithEncoding
        TTYStringIO = ui_testing.StringIOAsTTY
        for file_class, term, pb, expected_pb_class in (
            # on an xterm, either use them or not as the user requests,
            # otherwise default on
            (TTYStringIO, "xterm", "none", _mod_ui_text.NullProgressView),
            (TTYStringIO, "xterm", "text", _mod_ui_text.TextProgressView),
            (TTYStringIO, "xterm", None, _mod_ui_text.TextProgressView),
            # on a dumb terminal, again if there's explicit configuration
            # do it, otherwise default off
            (TTYStringIO, "dumb", "none", _mod_ui_text.NullProgressView),
            (TTYStringIO, "dumb", "text", _mod_ui_text.TextProgressView),
            (TTYStringIO, "dumb", None, _mod_ui_text.NullProgressView),
            # on a non-tty terminal, it's null regardless of $TERM
            (FileStringIO, "xterm", None, _mod_ui_text.NullProgressView),
            (FileStringIO, "dumb", None, _mod_ui_text.NullProgressView),
            # however, it can still be forced on
            (FileStringIO, "dumb", "text", _mod_ui_text.TextProgressView),
        ):
            self.overrideEnv("TERM", term)
            self.overrideEnv("BRZ_PROGRESS_BAR", pb)
            stdin = file_class("")
            stderr = file_class()
            stdout = file_class()
            uif = _mod_ui.make_ui_for_terminal(stdin, stdout, stderr)
            self.assertIsInstance(
                uif,
                _mod_ui_text.TextUIFactory,
                "TERM={} BRZ_PROGRESS_BAR={} uif={!r}".format(term, pb, uif),
            )
            self.assertIsInstance(
                uif.make_progress_view(),
                expected_pb_class,
                "TERM={} BRZ_PROGRESS_BAR={} uif={!r}".format(term, pb, uif),
            )

    def test_text_ui_non_terminal(self):
        """Even on non-ttys, make_ui_for_terminal gives a text ui."""
        stdin = stderr = stdout = ui_testing.StringIOWithEncoding()
        for term_type in ["dumb", None, "xterm"]:
            self.overrideEnv("TERM", term_type)
            uif = _mod_ui.make_ui_for_terminal(stdin, stdout, stderr)
            self.assertIsInstance(
                uif, _mod_ui_text.TextUIFactory, "TERM={!r}".format(term_type)
            )


class SilentUITests(tests.TestCase):
    def test_silent_factory_get_password(self):
        # A silent factory that can't do user interaction can't get a
        # password.  Possibly it should raise a more specific error but it
        # can't succeed.
        ui = _mod_ui.SilentUIFactory()
        stdout = ui_testing.StringIOWithEncoding()
        self.assertRaises(
            NotImplementedError,
            self.apply_redirected,
            None,
            stdout,
            stdout,
            ui.get_password,
        )
        # and it didn't write anything out either
        self.assertEqual("", stdout.getvalue())

    def test_silent_ui_getbool(self):
        factory = _mod_ui.SilentUIFactory()
        stdout = ui_testing.StringIOWithEncoding()
        self.assertRaises(
            NotImplementedError,
            self.apply_redirected,
            None,
            stdout,
            stdout,
            factory.get_boolean,
            "foo",
        )


class TestUIFactoryTests(tests.TestCase):
    def test_test_ui_factory_progress(self):
        # there's no output; we just want to make sure this doesn't crash -
        # see https://bugs.launchpad.net/bzr/+bug/408201
        ui = ui_testing.TestUIFactory()
        with ui.nested_progress_bar() as pb:
            pb.update("hello")
            pb.tick()


class CannedInputUIFactoryTests(tests.TestCase):
    def test_canned_input_get_input(self):
        uif = _mod_ui.CannedInputUIFactory([True, "mbp", "password", 42])
        self.assertEqual(True, uif.get_boolean("Extra cheese?"))
        self.assertEqual("mbp", uif.get_username("Enter your user name"))
        self.assertEqual(
            "password", uif.get_password("Password for %(host)s", host="example.com")
        )
        self.assertEqual(42, uif.get_integer("And all that jazz ?"))


class TestBoolFromString(tests.TestCase):
    def assertIsTrue(self, s, accepted_values=None):
        res = _mod_ui.bool_from_string(s, accepted_values=accepted_values)
        self.assertEqual(True, res)

    def assertIsFalse(self, s, accepted_values=None):
        res = _mod_ui.bool_from_string(s, accepted_values=accepted_values)
        self.assertEqual(False, res)

    def assertIsNone(self, s, accepted_values=None):
        res = _mod_ui.bool_from_string(s, accepted_values=accepted_values)
        self.assertIs(None, res)

    def test_know_valid_values(self):
        self.assertIsTrue("true")
        self.assertIsFalse("false")
        self.assertIsTrue("1")
        self.assertIsFalse("0")
        self.assertIsTrue("on")
        self.assertIsFalse("off")
        self.assertIsTrue("yes")
        self.assertIsFalse("no")
        self.assertIsTrue("y")
        self.assertIsFalse("n")
        # Also try some case variations
        self.assertIsTrue("True")
        self.assertIsFalse("False")
        self.assertIsTrue("On")
        self.assertIsFalse("Off")
        self.assertIsTrue("ON")
        self.assertIsFalse("OFF")
        self.assertIsTrue("oN")
        self.assertIsFalse("oFf")

    def test_invalid_values(self):
        self.assertIsNone(None)
        self.assertIsNone("doubt")
        self.assertIsNone("frue")
        self.assertIsNone("talse")
        self.assertIsNone("42")

    def test_provided_values(self):
        av = {"y": True, "n": False, "yes": True, "no": False}
        self.assertIsTrue("y", av)
        self.assertIsTrue("Y", av)
        self.assertIsTrue("Yes", av)
        self.assertIsFalse("n", av)
        self.assertIsFalse("N", av)
        self.assertIsFalse("No", av)
        self.assertIsNone("1", av)
        self.assertIsNone("0", av)
        self.assertIsNone("on", av)
        self.assertIsNone("off", av)


class TestConfirmationUserInterfacePolicy(tests.TestCase):
    def test_confirm_action_default(self):
        base_ui = _mod_ui.NoninteractiveUIFactory()
        for answer in [True, False]:
            self.assertEqual(
                _mod_ui.ConfirmationUserInterfacePolicy(
                    base_ui, answer, {}
                ).confirm_action("Do something?", "breezy.tests.do_something", {}),
                answer,
            )

    def test_confirm_action_specific(self):
        base_ui = _mod_ui.NoninteractiveUIFactory()
        for default_answer in [True, False]:
            for specific_answer in [True, False]:
                for conf_id in ["given_id", "other_id"]:
                    wrapper = _mod_ui.ConfirmationUserInterfacePolicy(
                        base_ui, default_answer, {"given_id": specific_answer}
                    )
                    result = wrapper.confirm_action("Do something?", conf_id, {})
                    if conf_id == "given_id":
                        self.assertEqual(result, specific_answer)
                    else:
                        self.assertEqual(result, default_answer)

    def test_repr(self):
        base_ui = _mod_ui.NoninteractiveUIFactory()
        wrapper = _mod_ui.ConfirmationUserInterfacePolicy(base_ui, True, {"a": 2})
        self.assertThat(
            repr(wrapper),
            Equals(
                "ConfirmationUserInterfacePolicy("
                "NoninteractiveUIFactory(), True, {'a': 2})"
            ),
        )


class TestProgressRecordingUI(tests.TestCase):
    """Test test-oriented UIFactory that records progress updates."""

    def test_nested_ignore_depth_beyond_one(self):
        # we only want to capture the first level out progress, not
        # want sub-components might do. So we have nested bars ignored.
        factory = ProgressRecordingUIFactory()
        pb1 = factory.nested_progress_bar()
        pb1.update("foo", 0, 1)
        pb2 = factory.nested_progress_bar()
        pb2.update("foo", 0, 1)
        pb2.finished()
        pb1.finished()
        self.assertEqual([("update", 0, 1, "foo")], factory._calls)
