# Copyright (C) 2009, 2010, 2011, 2016 Canonical Ltd
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

"""Tests run per UIFactory."""

# Testing UIFactories is a bit interesting because we require they all support a
# common interface, but the way they implement it can vary very widely.  Between
# text, batch-mode, graphical and other potential UIFactories, the requirements
# to set up a factory, to make it respond to requests, and to simulate user
# input can vary a lot.
#
# We want tests that therefore allow for the evaluation of the result to vary
# per implementation, but we want to check that the supported facilities are
# the same across all UIFactorys, unless they're specifically skipped.
#
# Our normal approach is to use test scenarios but that seems to just end up
# creating test-like objects inside the scenario.  Therefore we fall back to
# the older method of putting the common tests in a mixin.
#
# Plugins that add new UIFactorys can create their own subclasses.

from ... import tests, transport, ui
from ..ui_testing import StringIOAsTTY, TextUIFactory


class UIFactoryTestMixin:
    """Common tests for UIFactories.

    These are supposed to be expressed with no assumptions about how the
    UIFactory implements the method, only that it does implement them (or
    fails cleanly), and that the concrete subclass will make arrangements to
    build a factory and to examine its behaviour.

    Note that this is *not* a TestCase, because it can't be directly run, but
    the concrete subclasses should be.
    """

    def test_be_quiet(self):
        self.factory.be_quiet(True)
        self.assertEqual(True, self.factory.is_quiet())
        self.factory.be_quiet(False)
        self.assertEqual(False, self.factory.is_quiet())

    def test_confirm_action(self):
        # confirm_action should be answered by every ui factory; even
        # noninteractive ones should have a reasonable default
        self._load_responses([True])
        result = self.factory.confirm_action(
            "Break a lock?", "bzr.lock.break.confirm", {}
        )
        # will be true either because we read it from the input or because
        # that's the default
        self.assertEqual(result, True)

    def test_note(self):
        self.factory.note("a note to the user")
        self._check_note("a note to the user")

    def test_show_error(self):
        msg = "an error occurred"
        self.factory.show_error(msg)
        self._check_show_error(msg)

    def test_show_message(self):
        msg = "a message"
        self.factory.show_message(msg)
        self._check_show_message(msg)

    def test_show_warning(self):
        msg = "a warning"
        self.factory.show_warning(msg)
        self._check_show_warning(msg)

    def test_make_output_stream(self):
        # All UIs must now be able to at least accept output, even if they
        # just discard it.
        output_stream = self.factory.make_output_stream()
        output_stream.write("hello!")

    def test_transport_activity(self):
        # It doesn't matter what the implementation does, we just want to make
        # sure the interface is there
        t = transport.get_transport_from_url("memory:///")
        self.factory.report_transport_activity(t, 1000, "write")
        self.factory.report_transport_activity(t, 2000, "read")
        self.factory.report_transport_activity(t, 4000, None)
        self.factory.log_transport_activity()
        self._check_log_transport_activity_noarg()
        self.factory.log_transport_activity(display=True)
        self._check_log_transport_activity_display()

    def test_no_transport_activity(self):
        # No activity to report
        transport.get_transport_from_url("memory:///")
        self.factory.log_transport_activity(display=True)
        self._check_log_transport_activity_display_no_bytes()


class TestTextUIFactory(tests.TestCase, UIFactoryTestMixin):
    def setUp(self):
        super().setUp()
        self.factory = self._create_ui_factory()
        self.factory.__enter__()
        self.addCleanup(self.factory.__exit__, None, None, None)
        self.stdin = self.factory.stdin
        self.stdout = self.factory.stdout
        self.stderr = self.factory.stderr

    def _create_ui_factory(self):
        return TextUIFactory("")

    def _check_note(self, note_text):
        self.assertEqual(f"{note_text}\n", self.stdout.getvalue())

    def _check_show_error(self, msg):
        self.assertEqual(f"bzr: error: {msg}\n", self.stderr.getvalue())
        self.assertEqual("", self.stdout.getvalue())

    def _check_show_message(self, msg):
        self.assertEqual(f"{msg}\n", self.stdout.getvalue())
        self.assertEqual("", self.stderr.getvalue())

    def _check_show_warning(self, msg):
        self.assertEqual(f"bzr: warning: {msg}\n", self.stderr.getvalue())
        self.assertEqual("", self.stdout.getvalue())

    def _check_log_transport_activity_noarg(self):
        self.assertEqual("", self.stdout.getvalue())
        self.assertContainsRe(self.stderr.getvalue(), r"\d+kB\s+\dkB/s |")
        self.assertNotContainsRe(self.stderr.getvalue(), r"Transferred:")

    def _check_log_transport_activity_display(self):
        self.assertEqual("", self.stdout.getvalue())
        # Without a TTY, we shouldn't display anything
        self.assertEqual("", self.stderr.getvalue())

    def _check_log_transport_activity_display_no_bytes(self):
        self.assertEqual("", self.stdout.getvalue())
        # Without a TTY, we shouldn't display anything
        self.assertEqual("", self.stderr.getvalue())

    def _load_responses(self, responses):
        self.factory.stdin.seek(0)
        self.factory.stdin.writelines([((r and "y\n") or "n\n") for r in responses])
        self.factory.stdin.seek(0)


class TestTTYTextUIFactory(TestTextUIFactory):
    def _create_ui_factory(self):
        # Remove 'TERM' == 'dumb' which causes us to *not* treat output as a
        # real terminal, even though isatty returns True
        self.overrideEnv("TERM", None)
        return TextUIFactory("", StringIOAsTTY(), StringIOAsTTY())

    def _check_log_transport_activity_display(self):
        self.assertEqual("", self.stdout.getvalue())
        # Displaying the result should write to the progress stream using
        # base-10 units (see HACKING.txt).
        self.assertContainsRe(
            self.stderr.getvalue(),
            r"Transferred: 7kB" r" \(\d+\.\dkB/s r:2kB w:1kB u:4kB\)",
        )

    def _check_log_transport_activity_display_no_bytes(self):
        self.assertEqual("", self.stdout.getvalue())
        # Without actual bytes transferred, we should report nothing
        self.assertEqual("", self.stderr.getvalue())


class TestSilentUIFactory(tests.TestCase, UIFactoryTestMixin):
    # discards output, therefore tests for output expect nothing

    def setUp(self):
        super().setUp()
        self.factory = ui.SilentUIFactory()

    def _check_note(self, note_text):
        # it's just discarded
        pass

    def _check_show_error(self, msg):
        pass

    def _check_show_message(self, msg):
        pass

    def _check_show_warning(self, msg):
        pass

    def _check_log_transport_activity_noarg(self):
        pass

    def _check_log_transport_activity_display(self):
        pass

    def _check_log_transport_activity_display_no_bytes(self):
        pass

    def _load_responses(self, responses):
        pass


class TestCannedInputUIFactory(tests.TestCase, UIFactoryTestMixin):
    # discards output, reads input from variables

    def setUp(self):
        super().setUp()
        self.factory = ui.CannedInputUIFactory([])

    def _check_note(self, note_text):
        pass

    def _check_show_error(self, msg):
        pass

    def _check_show_message(self, msg):
        pass

    def _check_show_warning(self, msg):
        pass

    def _check_log_transport_activity_noarg(self):
        pass

    def _check_log_transport_activity_display(self):
        pass

    def _check_log_transport_activity_display_no_bytes(self):
        pass

    def _load_responses(self, responses):
        self.factory.responses.extend(responses)
