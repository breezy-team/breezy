# Copyright (C) 2005 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the bzrlib ui
"""

import os
from StringIO import StringIO
import re
import sys

import bzrlib
import bzrlib.errors as errors
from bzrlib.progress import DotsProgressBar, TTYProgressBar, ProgressBarStack
from bzrlib.tests import (
    TestUIFactory,
    StringIOWrapper,
    TestCase,
    )
from bzrlib.tests.test_progress import _TTYStringIO
from bzrlib.ui import SilentUIFactory
from bzrlib.ui.text import TextUIFactory


class UITests(TestCase):

    def test_silent_factory(self):
        ui = SilentUIFactory()
        stdout = StringIO()
        self.assertEqual(None,
                         self.apply_redirected(None, stdout, stdout,
                                               ui.get_password))
        self.assertEqual('', stdout.getvalue())
        # stdin should be empty
        self.assertEqual(None, ui.stdin.getline())
        self.assertEqual(None,
                         self.apply_redirected(None, stdout, stdout,
                                               ui.get_password,
                                               u'Hello\u1234 %(user)s',
                                               user=u'some\u1234'))
        self.assertEqual('', stdout.getvalue())
        # stdin should be empty
        self.assertEqual(None, ui.stdin.getline())

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
            self.assertEqual(None, ui.stdin.getline())
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
            self.assertEqual(None, ui.stdin.getline())
        finally:
            pb.finished()

    def test_progress_note(self):
        stderr = StringIO()
        stdout = StringIO()
        ui_factory = TextUIFactory(bar_type=TTYProgressBar)
        pb = ui_factory.nested_progress_bar()
        try:
            pb.to_messages_file = stdout
            ui_factory._progress_bar_stack.bottom().to_file = stderr
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
        ui_factory = TextUIFactory(bar_type=TTYProgressBar)
        pb = ui_factory.nested_progress_bar()
        try:
            pb.to_messages_file = stdout
            ui_factory._progress_bar_stack.bottom().to_file = stderr
            # Create a progress update that isn't throttled
            pb.start_time -= 10
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
        ui = TextUIFactory()
        pb1 = ui.nested_progress_bar()
        pb2 = ui.nested_progress_bar()
        self.assertRaises(errors.MissingProgressBarFinish, pb1.finished)
        pb2.finished()
        pb1.finished()

    def test_progress_stack(self):
        # test the progress bar stack which the default text factory 
        # uses.
        stderr = StringIO()
        stdout = StringIO()
        # make a stack, which accepts parameters like a pb.
        stack = ProgressBarStack(to_file=stderr, to_messages_file=stdout)
        # but is not one
        self.assertFalse(getattr(stack, 'note', False))
        pb1 = stack.get_nested()
        pb2 = stack.get_nested()
        self.assertRaises(errors.MissingProgressBarFinish, pb1.finished)
        pb2.finished()
        pb1.finished()
        # the text ui factory never actually removes the stack once its setup.
        # we need to be able to nest again correctly from here.
        pb1 = stack.get_nested()
        pb2 = stack.get_nested()
        self.assertRaises(errors.MissingProgressBarFinish, pb1.finished)
        pb2.finished()
        pb1.finished()

    def test_text_factory_setting_progress_bar(self):
        # we should be able to choose the progress bar type used.
        factory = bzrlib.ui.text.TextUIFactory(bar_type=DotsProgressBar)
        bar = factory.nested_progress_bar()
        bar.finished()
        self.assertIsInstance(bar, DotsProgressBar)

    def test_cli_stdin_is_default_stdin(self):
        factory = bzrlib.ui.CLIUIFactory()
        self.assertEqual(sys.stdin, factory.stdin)

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
        self.assertEqual(None, factory.stdin.getline())

    def test_silent_ui_getbool(self):
        factory = bzrlib.ui.SilentUIFactory()
        self.assert_get_bool_acceptance_of_user_input(factory)

    def test_silent_factory_prompts_silently(self):
        factory = bzrlib.ui.SilentUIFactory()
        stdout = StringIO()
        factory.stdin = StringIO("y\n")
        self.assertEqual(True,
                         self.apply_redirected(None, stdout, stdout,
                                               factory.get_boolean, "foo"))
        self.assertEqual("", stdout.getvalue())
        # stdin should be empty
        self.assertEqual(None, factory.stdin.getline())

    def test_text_ui_getbool(self):
        factory = bzrlib.ui.text.TextUIFactory()
        self.assert_get_bool_acceptance_of_user_input(factory)

    def test_text_factory_prompts_and_clears(self):
        # a get_boolean call should clear the pb before prompting
        factory = bzrlib.ui.text.TextUIFactory(bar_type=DotsProgressBar)
        factory.stdout = _TTYStringIO()
        factory.stdin = StringIO("yada\ny\n")
        pb = self.apply_redirected(factory.stdin, factory.stdout,
                                   factory.stdout, factory.nested_progress_bar)
        pb.start_time = None
        self.apply_redirected(factory.stdin, factory.stdout,
                              factory.stdout, pb.update, "foo", 0, 1)
        self.assertEqual(True,
                         self.apply_redirected(None, factory.stdout,
                                               factory.stdout,
                                               factory.get_boolean,
                                               "what do you want"))
        output = factory.stdout.getvalue()
        self.assertEqual("foo: .\n"
                         "what do you want? [y/n]: what do you want? [y/n]: ",
                         factory.stdout.getvalue())
        # stdin should be empty
        self.assertEqual(None, factory.stdin.getline())

