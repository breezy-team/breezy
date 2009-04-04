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

import bzrlib
import bzrlib.errors as errors
from bzrlib.progress import (
    DotsProgressBar,
    ProgressBarStack,
    ProgressTask,
    TTYProgressBar,
    )
from bzrlib.symbol_versioning import (
    deprecated_in,
    )
from bzrlib.tests import (
    TestCase,
    TestUIFactory,
    StringIOWrapper,
    )
from bzrlib.tests.test_progress import _TTYStringIO
from bzrlib.ui import (
    CLIUIFactory,
    SilentUIFactory,
    )
from bzrlib.ui.text import (
    TextProgressView,
    TextUIFactory,
    )


class UITests(TestCase):

    def test_silent_factory(self):
        ui = SilentUIFactory()
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
        ui = TestUIFactory(stdin='secret\n', stdout=StringIOWrapper())
        pb = ui.nested_progress_bar()
        try:
            self.assertEqual('secret',
                             self.apply_redirected(ui.stdin, ui.stdout,
                                                   ui.stdout,
                                                   ui.get_password))
            # ': ' is appended to prompt
            self.assertEqual(': ', ui.stdout.getvalue())
            # stdin should be empty
            self.assertEqual('', ui.stdin.readline())
        finally:
            pb.finished()

    def test_text_factory_utf8_password(self):
        """Test an utf8 password.

        We can't predict what encoding users will have for stdin, so we force
        it to utf8 to test that we transport the password correctly.
        """
        ui = TestUIFactory(stdin=u'baz\u1234'.encode('utf8'),
                           stdout=StringIOWrapper())
        ui.stdin.encoding = 'utf8'
        ui.stdout.encoding = ui.stdin.encoding
        pb = ui.nested_progress_bar()
        try:
            password = self.apply_redirected(ui.stdin, ui.stdout, ui.stdout,
                                             ui.get_password,
                                             u'Hello \u1234 %(user)s',
                                             user=u'some\u1234')
            # We use StringIO objects, we need to decode them
            self.assertEqual(u'baz\u1234', password.decode('utf8'))
            self.assertEqual(u'Hello \u1234 some\u1234: ',
                             ui.stdout.getvalue().decode('utf8'))
            # stdin should be empty
            self.assertEqual('', ui.stdin.readline())
        finally:
            pb.finished()

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
        stderr = StringIO()
        stdout = StringIO()
        # The PQM redirects the output to a file, so it
        # defaults to creating a Dots progress bar. we
        # need to force it to believe we are a TTY
        ui_factory = TextUIFactory(
            stdin=StringIO(''),
            stdout=stdout, stderr=stderr)
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

    def test_progress_stack(self):
        # test the progress bar stack which the default text factory
        # uses.
        stderr = StringIO()
        stdout = StringIO()
        # make a stack, which accepts parameters like a pb.
        stack = self.applyDeprecated(
            deprecated_in((1, 12, 0)),
            ProgressBarStack,
            to_file=stderr, to_messages_file=stdout)
        # but is not one
        self.assertFalse(getattr(stack, 'note', False))
        pb1 = stack.get_nested()
        pb2 = stack.get_nested()
        warnings, _ = self.callCatchWarnings(pb1.finished)
        self.assertEqual(len(warnings), 1)
        pb2.finished()
        pb1.finished()
        # the text ui factory never actually removes the stack once its setup.
        # we need to be able to nest again correctly from here.
        pb1 = stack.get_nested()
        pb2 = stack.get_nested()
        warnings, _ = self.callCatchWarnings(pb1.finished)
        self.assertEqual(len(warnings), 1)
        pb2.finished()
        pb1.finished()

    def assert_get_bool_acceptance_of_user_input(self, factory):
        factory.stdin = StringIO("y\nyes with garbage\n"
                                 "yes\nn\nnot an answer\n"
                                 "no\nfoo\n")
        factory.stdout = StringIO()
        # there is no output from the base factory
        self.assertEqual(True, factory.get_boolean(""))
        self.assertEqual(True, factory.get_boolean(""))
        self.assertEqual(False, factory.get_boolean(""))
        self.assertEqual(False, factory.get_boolean(""))
        self.assertEqual("foo\n", factory.stdin.read())
        # stdin should be empty
        self.assertEqual('', factory.stdin.readline())

    def test_silent_ui_getbool(self):
        factory = SilentUIFactory()
        self.assert_get_bool_acceptance_of_user_input(factory)

    def test_silent_factory_prompts_silently(self):
        factory = SilentUIFactory()
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

    def test_text_factory_prompts_and_clears(self):
        # a get_boolean call should clear the pb before prompting
        out = _TTYStringIO()
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


class TestTextProgressView(TestCase):
    """Tests for text display of progress bars.
    """
    # XXX: These might be a bit easier to write if the rendering and
    # state-maintaining parts of TextProgressView were more separate, and if
    # the progress task called back directly to its own view not to the ui
    # factory. -- mbp 20090312
    
    def _make_factory(self):
        out = StringIO()
        uif = TextUIFactory(stderr=out)
        uif._progress_view._width = 80
        return out, uif

    def test_render_progress_easy(self):
        """Just one task and one quarter done"""
        out, uif = self._make_factory()
        task = uif.nested_progress_bar()
        task.update('reticulating splines', 5, 20)
        self.assertEqual(
'\r[####/               ] reticulating splines 5/20                               \r'
            , out.getvalue())

    def test_render_progress_nested(self):
        """Tasks proportionally contribute to overall progress"""
        out, uif = self._make_factory()
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
        out, uif = self._make_factory()
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

