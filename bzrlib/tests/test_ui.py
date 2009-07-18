# Copyright (C) 2005, 2008, 2009 Canonical Ltd
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

"""Tests for the bzrlib ui
"""

import os
from StringIO import StringIO
import re
import sys
import time

from bzrlib import (
    errors,
    tests,
    ui as _mod_ui,
    )
from bzrlib.symbol_versioning import (
    deprecated_in,
    )
from bzrlib.tests import (
    TestCase,
    TestUIFactory,
    StringIOWrapper,
    )
from bzrlib.tests.test_progress import (
    _NonTTYStringIO,
    _TTYStringIO,
    )
from bzrlib.ui import (
    CLIUIFactory,
    SilentUIFactory,
    UIFactory,
    make_ui_for_terminal,
    )
from bzrlib.ui.text import (
    NullProgressView,
    TextProgressView,
    TextUIFactory,
    )


class UITests(tests.TestCase):

    def test_silent_factory(self):
        ui = _mod_ui.SilentUIFactory()
        stdout = StringIO()
        self.assertEqual(None,
                         self.apply_redirected(None, stdout, stdout,
                                               ui.get_password))
        self.assertEqual('', stdout.getvalue())
        self.assertEqual(None,
                         self.apply_redirected(None, stdout, stdout,
                                               ui.get_password,
                                               u'Hello\u1234 %(user)s',
                                               user=u'some\u1234'))
        self.assertEqual('', stdout.getvalue())

    def test_text_factory_ascii_password(self):
        ui = tests.TestUIFactory(stdin='secret\n',
                                 stdout=tests.StringIOWrapper(),
                                 stderr=tests.StringIOWrapper())
        pb = ui.nested_progress_bar()
        try:
            self.assertEqual('secret',
                             self.apply_redirected(ui.stdin, ui.stdout,
                                                   ui.stderr,
                                                   ui.get_password))
            # ': ' is appended to prompt
            self.assertEqual(': ', ui.stderr.getvalue())
            self.assertEqual('', ui.stdout.readline())
            # stdin should be empty
            self.assertEqual('', ui.stdin.readline())
        finally:
            pb.finished()

    def test_text_factory_utf8_password(self):
        """Test an utf8 password.

        We can't predict what encoding users will have for stdin, so we force
        it to utf8 to test that we transport the password correctly.
        """
        ui = tests.TestUIFactory(stdin=u'baz\u1234'.encode('utf8'),
                                 stdout=tests.StringIOWrapper(),
                                 stderr=tests.StringIOWrapper())
        ui.stderr.encoding = ui.stdout.encoding = ui.stdin.encoding = 'utf8'
        pb = ui.nested_progress_bar()
        try:
            password = self.apply_redirected(ui.stdin, ui.stdout, ui.stderr,
                                             ui.get_password,
                                             u'Hello \u1234 %(user)s',
                                             user=u'some\u1234')
            # We use StringIO objects, we need to decode them
            self.assertEqual(u'baz\u1234', password.decode('utf8'))
            self.assertEqual(u'Hello \u1234 some\u1234: ',
                             ui.stderr.getvalue().decode('utf8'))
            # stdin and stdout should be empty
            self.assertEqual('', ui.stdin.readline())
            self.assertEqual('', ui.stdout.readline())
        finally:
            pb.finished()

    def test_progress_construction(self):
        """TextUIFactory constructs the right progress view.
        """
        for (term, pb, expected_pb_class) in (
            # on an xterm, either use them or not as the user requests,
            # otherwise default on
            ('xterm', 'none', NullProgressView),
            ('xterm', 'text', TextProgressView),
            ('xterm', None, TextProgressView),
            # on a dumb terminal, again if there's explicit configuration do
            # it, otherwise default off
            ('dumb', 'none', NullProgressView),
            ('dumb', 'text', TextProgressView),
            ('dumb', None, NullProgressView),
            ):
            os.environ['TERM'] = term
            if pb is None:
                del os.environ['BZR_PROGRESS_BAR']
            else:
                os.environ['BZR_PROGRESS_BAR'] = pb
            stdin = _TTYStringIO('')
            stderr = _TTYStringIO()
            stdout = _TTYStringIO()
            uif = make_ui_for_terminal(stdin, stdout, stderr)
            self.assertIsInstance(uif.make_progress_view(),
                expected_pb_class,
                "TERM=%s BZR_PROGRESS_BAR=%s uif=%r" % (term, pb, uif,))

    def test_text_ui_non_terminal(self):
        """Even on non-ttys, make_ui_for_terminal gives a text ui."""
        stdin = _NonTTYStringIO('')
        stderr = _NonTTYStringIO()
        stdout = _NonTTYStringIO()
        for term_type in ['dumb', None, 'xterm']:
            if term_type is None:
                del os.environ['TERM']
            else:
                os.environ['TERM'] = term_type
            uif = make_ui_for_terminal(stdin, stdout, stderr)
            self.assertIsInstance(uif, TextUIFactory,
                'TERM=%r' % (term_type,))

    def test_progress_note(self):
        stderr = StringIO()
        stdout = StringIO()
        ui_factory = TextUIFactory(stdin=StringIO(''),
            stderr=stderr,
            stdout=stdout)
        pb = ui_factory.nested_progress_bar()
        try:
            result = pb.note('t')
            self.assertEqual(None, result)
            self.assertEqual("t\n", stdout.getvalue())
            # Since there was no update() call, there should be no clear() call
            self.failIf(re.search(r'^\r {10,}\r$',
                                  stderr.getvalue()) is not None,
                        'We cleared the stderr without anything to put there')
        finally:
            pb.finished()

    def test_progress_note_clears(self):
        stderr = _TTYStringIO()
        stdout = _TTYStringIO()
        # so that we get a TextProgressBar
        os.environ['TERM'] = 'xterm'
        ui_factory = TextUIFactory(
            stdin=StringIO(''),
            stdout=stdout, stderr=stderr)
        self.assertIsInstance(ui_factory._progress_view,
            TextProgressView)
        pb = ui_factory.nested_progress_bar()
        try:
            # Create a progress update that isn't throttled
            pb.update('x', 1, 1)
            result = pb.note('t')
            self.assertEqual(None, result)
            self.assertEqual("t\n", stdout.getvalue())
            # the exact contents will depend on the terminal width and we don't
            # care about that right now - but you're probably running it on at
            # least a 10-character wide terminal :)
            self.assertContainsRe(stderr.getvalue(), r'\r {10,}\r$')
        finally:
            pb.finished()

    def test_progress_nested(self):
        # test factory based nested and popping.
        ui = TextUIFactory(None, None, None)
        pb1 = ui.nested_progress_bar()
        pb2 = ui.nested_progress_bar()
        # You do get a warning if the outermost progress bar wasn't finished
        # first - it's not clear if this is really useful or if it should just
        # become orphaned -- mbp 20090120
        warnings, _ = self.callCatchWarnings(pb1.finished)
        if len(warnings) != 1:
            self.fail("unexpected warnings: %r" % (warnings,))
        pb2.finished()
        pb1.finished()

    def assert_get_bool_acceptance_of_user_input(self, factory):
        factory.stdin = StringIO("y\nyes with garbage\n"
                                 "yes\nn\nnot an answer\n"
                                 "no\n"
                                 "N\nY\n"
                                 "foo\n"
                                )
        factory.stdout = StringIO()
        factory.stderr = StringIO()
        # there is no output from the base factory
        self.assertEqual(True, factory.get_boolean(""))
        self.assertEqual(True, factory.get_boolean(""))
        self.assertEqual(False, factory.get_boolean(""))
        self.assertEqual(False, factory.get_boolean(""))
        self.assertEqual(False, factory.get_boolean(""))
        self.assertEqual(True, factory.get_boolean(""))
        self.assertEqual("foo\n", factory.stdin.read())
        # stdin should be empty
        self.assertEqual('', factory.stdin.readline())

    def test_silent_ui_getbool(self):
        factory = _mod_ui.SilentUIFactory()
        self.assert_get_bool_acceptance_of_user_input(factory)

    def test_silent_factory_prompts_silently(self):
        factory = _mod_ui.SilentUIFactory()
        stdout = StringIO()
        factory.stdin = StringIO("y\n")
        self.assertEqual(True,
                         self.apply_redirected(None, stdout, stdout,
                                               factory.get_boolean, "foo"))
        self.assertEqual("", stdout.getvalue())
        # stdin should be empty
        self.assertEqual('', factory.stdin.readline())

    def test_text_ui_getbool(self):
        factory = TextUIFactory(None, None, None)
        self.assert_get_bool_acceptance_of_user_input(factory)

    def test_text_factory_prompt(self):
        # see <https://launchpad.net/bugs/365891>
        factory = TextUIFactory(StringIO(), StringIO(), StringIO())
        factory.prompt('foo %2e')
        self.assertEqual('', factory.stdout.getvalue())
        self.assertEqual('foo %2e', factory.stderr.getvalue())

    def test_text_factory_prompts_and_clears(self):
        # a get_boolean call should clear the pb before prompting
        out = _TTYStringIO()
        os.environ['TERM'] = 'xterm'
        factory = TextUIFactory(stdin=StringIO("yada\ny\n"), stdout=out, stderr=out)
        pb = factory.nested_progress_bar()
        pb.show_bar = False
        pb.show_spinner = False
        pb.show_count = False
        pb.update("foo", 0, 1)
        self.assertEqual(True,
                         self.apply_redirected(None, factory.stdout,
                                               factory.stdout,
                                               factory.get_boolean,
                                               "what do you want"))
        output = out.getvalue()
        self.assertContainsRe(factory.stdout.getvalue(),
            "foo *\r\r  *\r*")
        self.assertContainsRe(factory.stdout.getvalue(),
            r"what do you want\? \[y/n\]: what do you want\? \[y/n\]: ")
        # stdin should have been totally consumed
        self.assertEqual('', factory.stdin.readline())

    def test_text_tick_after_update(self):
        ui_factory = TextUIFactory(stdout=StringIO(), stderr=StringIO())
        pb = ui_factory.nested_progress_bar()
        try:
            pb.update('task', 0, 3)
            # Reset the clock, so that it actually tries to repaint itself
            ui_factory._progress_view._last_repaint = time.time() - 1.0
            pb.tick()
        finally:
            pb.finished()

    def test_text_ui_getusername(self):
        factory = TextUIFactory(None, None, None)
        factory.stdin = StringIO("someuser\n\n")
        factory.stdout = StringIO()
        factory.stderr = StringIO()
        factory.stdout.encoding = "utf8"
        # there is no output from the base factory
        self.assertEqual("someuser",
                         factory.get_username('Hello %(host)s', host='some'))
        self.assertEquals("Hello some: ", factory.stderr.getvalue())
        self.assertEquals('', factory.stdout.getvalue())
        self.assertEqual("", factory.get_username("Gebruiker"))
        # stdin should be empty
        self.assertEqual('', factory.stdin.readline())

    def test_text_ui_getusername_utf8(self):
        ui = tests.TestUIFactory(stdin=u'someuser\u1234'.encode('utf8'),
                                 stdout=tests.StringIOWrapper(),
                                 stderr=tests.StringIOWrapper())
        ui.stderr.encoding = ui.stdout.encoding = ui.stdin.encoding = "utf8"
        pb = ui.nested_progress_bar()
        try:
            # there is no output from the base factory
            username = self.apply_redirected(ui.stdin, ui.stdout, ui.stderr,
                ui.get_username, u'Hello\u1234 %(host)s', host=u'some\u1234')
            self.assertEquals(u"someuser\u1234", username.decode('utf8'))
            self.assertEquals(u"Hello\u1234 some\u1234: ",
                              ui.stderr.getvalue().decode("utf8"))
            self.assertEquals('', ui.stdout.getvalue())
        finally:
            pb.finished()


class CLIUITests(TestCase):

    def test_cli_factory_deprecated(self):
        uif = self.applyDeprecated(deprecated_in((1, 18, 0)),
            CLIUIFactory,
            StringIO(), StringIO(), StringIO())
        self.assertIsInstance(uif, UIFactory)


class SilentUITests(TestCase):

    def test_silent_factory(self):
        ui = SilentUIFactory()
        stdout = StringIO()
        self.assertRaises(
            NotImplementedError,
            self.apply_redirected,
            None, stdout, stdout, ui.get_password)
        # and it didn't write anything out either
        self.assertEqual('', stdout.getvalue())

    def test_silent_ui_getbool(self):
        factory = SilentUIFactory()
        stdout = StringIO()
        self.assertRaises(
            NotImplementedError,
            self.apply_redirected,
            None, stdout, stdout, factory.get_boolean, "foo")


class TestTextProgressView(tests.TestCase):
    """Tests for text display of progress bars.

    These test the behaviour of what's written to the output, rather than the
    path-independent display of any particular state.  It may be worth adding
    some tests of the second kind too as they'll be less brittle.
    """
    
    def _make_factory(self):
        stderr = _TTYStringIO()
        uif = TextUIFactory(stderr=stderr)
        uif._progress_view._width = 80
        return stderr, uif

    def test_render_progress_easy(self):
        """Just one task and one quarter done"""
        stderr, uif = self._make_factory()
        task = uif.nested_progress_bar()
        task.update('reticulating splines', 5, 20)
        self.assertEqual(
'\r[####/               ] reticulating splines 5/20                               \r'
            , stderr.getvalue())

    def test_render_progress_nested(self):
        """Tasks proportionally contribute to overall progress"""
        stderr, uif = self._make_factory()
        task = uif.nested_progress_bar()
        task.update('reticulating splines', 0, 2)
        task2 = uif.nested_progress_bar()
        task2.update('stage2', 1, 2)
        # so we're in the first half of the main task, and half way through
        # that
        self.assertEqual(
r'[####\               ] reticulating splines:stage2 1/2'
            , uif._progress_view._render_line())
        # if the nested task is complete, then we're all the way through the
        # first half of the overall work
        task2.update('stage2', 2, 2)
        self.assertEqual(
r'[#########|          ] reticulating splines:stage2 2/2'
            , uif._progress_view._render_line())

    def test_render_progress_sub_nested(self):
        """Intermediate tasks don't mess up calculation."""
        stderr, uif = self._make_factory()
        task_a = uif.nested_progress_bar()
        task_a.update('a', 0, 2)
        task_b = uif.nested_progress_bar()
        task_b.update('b')
        task_c = uif.nested_progress_bar()
        task_c.update('c', 1, 2)
        # the top-level task is in its first half; the middle one has no
        # progress indication, just a label; and the bottom one is half done,
        # so the overall fraction is 1/4
        self.assertEqual(
            r'[####|               ] a:b:c 1/2'
            , uif._progress_view._render_line())
