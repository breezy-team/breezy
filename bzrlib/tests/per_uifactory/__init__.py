# Copyright (C) 2009, 2010 Canonical Ltd
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


from cStringIO import StringIO
import unittest


from bzrlib import (
    tests,
    transport,
    ui,
    )


class UIFactoryTestMixin(object):
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
        self.assertEquals(True, self.factory.is_quiet())
        self.factory.be_quiet(False)
        self.assertEquals(False, self.factory.is_quiet())

    def test_note(self):
        self.factory.note("a note to the user")
        self._check_note("a note to the user")

    def test_show_error(self):
        msg = 'an error occurred'
        self.factory.show_error(msg)
        self._check_show_error(msg)

    def test_show_message(self):
        msg = 'a message'
        self.factory.show_message(msg)
        self._check_show_message(msg)

    def test_show_warning(self):
        msg = 'a warning'
        self.factory.show_warning(msg)
        self._check_show_warning(msg)

    def test_make_output_stream(self):
        # All UIs must now be able to at least accept output, even if they
        # just discard it.
        output_stream = self.factory.make_output_stream()
        output_stream.write('hello!')

    def test_transport_activity(self):
        # It doesn't matter what the implementation does, we just want to make
        # sure the interface is there
        t = transport.get_transport('memory:///')
        self.factory.report_transport_activity(t, 1000, 'write')
        self.factory.report_transport_activity(t, 2000, 'read')
        self.factory.report_transport_activity(t, 4000, None)
        self.factory.log_transport_activity()
        self._check_log_transport_activity_noarg()
        self.factory.log_transport_activity(display=True)
        self._check_log_transport_activity_display()

    def test_no_transport_activity(self):
        # No activity to report
        t = transport.get_transport('memory:///')
        self.factory.log_transport_activity(display=True)
        self._check_log_transport_activity_display_no_bytes()


class TestTextUIFactory(tests.TestCase, UIFactoryTestMixin):

    def setUp(self):
        super(TestTextUIFactory, self).setUp()
        self.stdin = StringIO()
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.factory = ui.text.TextUIFactory(self.stdin, self.stdout,
            self.stderr)

    def _check_note(self, note_text):
        self.assertEquals("%s\n" % note_text,
            self.stdout.getvalue())

    def _check_show_error(self, msg):
        self.assertEquals("bzr: error: %s\n" % msg,
            self.stderr.getvalue())
        self.assertEquals("", self.stdout.getvalue())

    def _check_show_message(self, msg):
        self.assertEquals("%s\n" % msg,
            self.stdout.getvalue())
        self.assertEquals("", self.stderr.getvalue())

    def _check_show_warning(self, msg):
        self.assertEquals("bzr: warning: %s\n" % msg,
            self.stderr.getvalue())
        self.assertEquals("", self.stdout.getvalue())

    def _check_log_transport_activity_noarg(self):
        self.assertEqual('', self.stdout.getvalue())
        self.assertContainsRe(self.stderr.getvalue(), r'\d+KB\s+\dKB/s |')
        self.assertNotContainsRe(self.stderr.getvalue(), r'Transferred:')

    def _check_log_transport_activity_display(self):
        self.assertEqual('', self.stdout.getvalue())
        # Without a TTY, we shouldn't display anything
        self.assertEqual('', self.stderr.getvalue())

    def _check_log_transport_activity_display_no_bytes(self):
        self.assertEqual('', self.stdout.getvalue())
        # Without a TTY, we shouldn't display anything
        self.assertEqual('', self.stderr.getvalue())


class TestTTYTextUIFactory(TestTextUIFactory):

    def setUp(self):
        super(TestTTYTextUIFactory, self).setUp()

        class TTYStringIO(object):
            """Thunk over to StringIO() for everything but 'isatty'"""

            def __init__(self):
                self.__dict__['_sio'] = StringIO()

            def isatty(self):
                return True

            def __getattr__(self, name):
                return getattr(self._sio, name)

            def __setattr__(self, name, value):
                return setattr(self._sio, name, value)
                
        # Remove 'TERM' == 'dumb' which causes us to *not* treat output as a
        # real terminal, even though isatty returns True
        self._captureVar('TERM', None)
        self.stderr = TTYStringIO()
        self.stdout = TTYStringIO()
        self.factory = ui.text.TextUIFactory(self.stdin, self.stdout,
            self.stderr)

    def _check_log_transport_activity_display(self):
        self.assertEqual('', self.stdout.getvalue())
        # Displaying the result should write to the progress stream
        self.assertContainsRe(self.stderr.getvalue(),
            r'Transferred: 7KiB'
            r' \(\d+\.\dK/s r:2K w:1K u:4K\)')

    def _check_log_transport_activity_display_no_bytes(self):
        self.assertEqual('', self.stdout.getvalue())
        # Without actual bytes transferred, we should report nothing
        self.assertEqual('', self.stderr.getvalue())


class TestSilentUIFactory(tests.TestCase, UIFactoryTestMixin):
    # discards output, therefore tests for output expect nothing

    def setUp(self):
        super(TestSilentUIFactory, self).setUp()
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


class TestCannedInputUIFactory(tests.TestCase, UIFactoryTestMixin):
    # discards output, reads input from variables

    def setUp(self):
        super(TestCannedInputUIFactory, self).setUp()
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
