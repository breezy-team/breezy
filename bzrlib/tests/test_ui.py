# Copyright (C) 2005-2010 Canonical Ltd
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
import re
import time

from StringIO import StringIO

from bzrlib import (
    errors,
    remote,
    repository,
    tests,
    ui as _mod_ui,
    )
from bzrlib.symbol_versioning import (
    deprecated_in,
    )
from bzrlib.tests import test_progress
from bzrlib.ui import text as _mod_ui_text


class TestTextUIFactory(tests.TestCase):

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

    def test_progress_note(self):
        stderr = tests.StringIOWrapper()
        stdout = tests.StringIOWrapper()
        ui_factory = _mod_ui_text.TextUIFactory(stdin=tests.StringIOWrapper(''),
                                                stderr=stderr,
                                                stdout=stdout)
        pb = ui_factory.nested_progress_bar()
        try:
            result = self.applyDeprecated(deprecated_in((2, 1, 0)),
                pb.note,
                't')
            self.assertEqual(None, result)
            self.assertEqual("t\n", stdout.getvalue())
            # Since there was no update() call, there should be no clear() call
            self.failIf(re.search(r'^\r {10,}\r$',
                                  stderr.getvalue()) is not None,
                        'We cleared the stderr without anything to put there')
        finally:
            pb.finished()

    def test_progress_note_clears(self):
        stderr = test_progress._TTYStringIO()
        stdout = test_progress._TTYStringIO()
        # so that we get a TextProgressBar
        os.environ['TERM'] = 'xterm'
        ui_factory = _mod_ui_text.TextUIFactory(
            stdin=tests.StringIOWrapper(''),
            stdout=stdout, stderr=stderr)
        self.assertIsInstance(ui_factory._progress_view,
                              _mod_ui_text.TextProgressView)
        pb = ui_factory.nested_progress_bar()
        try:
            # Create a progress update that isn't throttled
            pb.update('x', 1, 1)
            result = self.applyDeprecated(deprecated_in((2, 1, 0)),
                pb.note, 't')
            self.assertEqual(None, result)
            self.assertEqual("t\n", stdout.getvalue())
            # the exact contents will depend on the terminal width and we don't
            # care about that right now - but you're probably running it on at
            # least a 10-character wide terminal :)
            self.assertContainsRe(stderr.getvalue(), r'\r {10,}\r$')
        finally:
            pb.finished()

    def test_text_ui_get_boolean(self):
        stdin = tests.StringIOWrapper("y\n" # True
                                      "n\n" # False
                                      "yes with garbage\nY\n" # True
                                      "not an answer\nno\n" # False
                                      "I'm sure!\nyes\n" # True
                                      "NO\n" # False
                                      "foo\n")
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        factory = _mod_ui_text.TextUIFactory(stdin, stdout, stderr)
        self.assertEqual(True, factory.get_boolean(""))
        self.assertEqual(False, factory.get_boolean(""))
        self.assertEqual(True, factory.get_boolean(""))
        self.assertEqual(False, factory.get_boolean(""))
        self.assertEqual(True, factory.get_boolean(""))
        self.assertEqual(False, factory.get_boolean(""))
        self.assertEqual("foo\n", factory.stdin.read())
        # stdin should be empty
        self.assertEqual('', factory.stdin.readline())

    def test_text_ui_get_integer(self):
        stdin = tests.StringIOWrapper(
            "1\n"
            "  -2  \n"
            "hmmm\nwhat else ?\nCome on\nok 42\n4.24\n42\n")
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        factory = _mod_ui_text.TextUIFactory(stdin, stdout, stderr)
        self.assertEqual(1, factory.get_integer(""))
        self.assertEqual(-2, factory.get_integer(""))
        self.assertEqual(42, factory.get_integer(""))

    def test_text_factory_prompt(self):
        # see <https://launchpad.net/bugs/365891>
        StringIO = tests.StringIOWrapper
        factory = _mod_ui_text.TextUIFactory(StringIO(), StringIO(), StringIO())
        factory.prompt('foo %2e')
        self.assertEqual('', factory.stdout.getvalue())
        self.assertEqual('foo %2e', factory.stderr.getvalue())

    def test_text_factory_prompts_and_clears(self):
        # a get_boolean call should clear the pb before prompting
        out = test_progress._TTYStringIO()
        os.environ['TERM'] = 'xterm'
        factory = _mod_ui_text.TextUIFactory(
            stdin=tests.StringIOWrapper("yada\ny\n"),
            stdout=out, stderr=out)
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
        ui_factory = _mod_ui_text.TextUIFactory(stdout=tests.StringIOWrapper(),
                                                stderr=tests.StringIOWrapper())
        pb = ui_factory.nested_progress_bar()
        try:
            pb.update('task', 0, 3)
            # Reset the clock, so that it actually tries to repaint itself
            ui_factory._progress_view._last_repaint = time.time() - 1.0
            pb.tick()
        finally:
            pb.finished()

    def test_text_ui_getusername(self):
        factory = _mod_ui_text.TextUIFactory(None, None, None)
        factory.stdin = tests.StringIOWrapper("someuser\n\n")
        factory.stdout = tests.StringIOWrapper()
        factory.stderr = tests.StringIOWrapper()
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

    def test_quietness(self):
        os.environ['BZR_PROGRESS_BAR'] = 'text'
        ui_factory = _mod_ui_text.TextUIFactory(None,
            test_progress._TTYStringIO(),
            test_progress._TTYStringIO())
        self.assertIsInstance(ui_factory._progress_view,
            _mod_ui_text.TextProgressView)
        ui_factory.be_quiet(True)
        self.assertIsInstance(ui_factory._progress_view,
            _mod_ui_text.NullProgressView)

    def test_text_ui_show_user_warning(self):
        from bzrlib.repofmt.groupcompress_repo import RepositoryFormat2a
        from bzrlib.repofmt.pack_repo import RepositoryFormatKnitPack5
        err = StringIO()
        out = StringIO()
        ui = tests.TextUIFactory(stdin=None, stdout=out, stderr=err)
        remote_fmt = remote.RemoteRepositoryFormat()
        remote_fmt._network_name = RepositoryFormatKnitPack5().network_name()
        ui.show_user_warning('cross_format_fetch', from_format=RepositoryFormat2a(),
            to_format=remote_fmt)
        self.assertEquals('', out.getvalue())
        self.assertEquals("Doing on-the-fly conversion from RepositoryFormat2a() to "
            "RemoteRepositoryFormat(_network_name='Bazaar RepositoryFormatKnitPack5 "
            "(bzr 1.6)\\n').\nThis may take some time. Upgrade the repositories to "
            "the same format for better performance.\n",
            err.getvalue())
        # and now with it suppressed please
        err = StringIO()
        out = StringIO()
        ui = tests.TextUIFactory(stdin=None, stdout=out, stderr=err)
        ui.suppressed_warnings.add('cross_format_fetch')
        ui.show_user_warning('cross_format_fetch', from_format=RepositoryFormat2a(),
            to_format=remote_fmt)
        self.assertEquals('', out.getvalue())
        self.assertEquals('', err.getvalue())


class TestTextUIOutputStream(tests.TestCase):
    """Tests for output stream that synchronizes with progress bar."""

    def test_output_clears_terminal(self):
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        clear_calls = []

        uif =  _mod_ui_text.TextUIFactory(None, stdout, stderr)
        uif.clear_term = lambda: clear_calls.append('clear')

        stream = _mod_ui_text.TextUIOutputStream(uif, uif.stdout)
        stream.write("Hello world!\n")
        stream.write("there's more...\n")
        stream.writelines(["1\n", "2\n", "3\n"])

        self.assertEqual(stdout.getvalue(),
            "Hello world!\n"
            "there's more...\n"
            "1\n2\n3\n")
        self.assertEqual(['clear', 'clear', 'clear'],
            clear_calls)

        stream.flush()


class UITests(tests.TestCase):

    def test_progress_construction(self):
        """TextUIFactory constructs the right progress view.
        """
        TTYStringIO = test_progress._TTYStringIO
        FileStringIO = tests.StringIOWrapper
        for (file_class, term, pb, expected_pb_class) in (
            # on an xterm, either use them or not as the user requests,
            # otherwise default on
            (TTYStringIO, 'xterm', 'none', _mod_ui_text.NullProgressView),
            (TTYStringIO, 'xterm', 'text', _mod_ui_text.TextProgressView),
            (TTYStringIO, 'xterm', None, _mod_ui_text.TextProgressView),
            # on a dumb terminal, again if there's explicit configuration do
            # it, otherwise default off
            (TTYStringIO, 'dumb', 'none', _mod_ui_text.NullProgressView),
            (TTYStringIO, 'dumb', 'text', _mod_ui_text.TextProgressView),
            (TTYStringIO, 'dumb', None, _mod_ui_text.NullProgressView),
            # on a non-tty terminal, it's null regardless of $TERM
            (FileStringIO, 'xterm', None, _mod_ui_text.NullProgressView),
            (FileStringIO, 'dumb', None, _mod_ui_text.NullProgressView),
            # however, it can still be forced on
            (FileStringIO, 'dumb', 'text', _mod_ui_text.TextProgressView),
            ):
            os.environ['TERM'] = term
            if pb is None:
                if 'BZR_PROGRESS_BAR' in os.environ:
                    del os.environ['BZR_PROGRESS_BAR']
            else:
                os.environ['BZR_PROGRESS_BAR'] = pb
            stdin = file_class('')
            stderr = file_class()
            stdout = file_class()
            uif = _mod_ui.make_ui_for_terminal(stdin, stdout, stderr)
            self.assertIsInstance(uif, _mod_ui_text.TextUIFactory,
                "TERM=%s BZR_PROGRESS_BAR=%s uif=%r" % (term, pb, uif,))
            self.assertIsInstance(uif.make_progress_view(),
                expected_pb_class,
                "TERM=%s BZR_PROGRESS_BAR=%s uif=%r" % (term, pb, uif,))

    def test_text_ui_non_terminal(self):
        """Even on non-ttys, make_ui_for_terminal gives a text ui."""
        stdin = test_progress._NonTTYStringIO('')
        stderr = test_progress._NonTTYStringIO()
        stdout = test_progress._NonTTYStringIO()
        for term_type in ['dumb', None, 'xterm']:
            if term_type is None:
                del os.environ['TERM']
            else:
                os.environ['TERM'] = term_type
            uif = _mod_ui.make_ui_for_terminal(stdin, stdout, stderr)
            self.assertIsInstance(uif, _mod_ui_text.TextUIFactory,
                'TERM=%r' % (term_type,))


class SilentUITests(tests.TestCase):

    def test_silent_factory_get_password(self):
        # A silent factory that can't do user interaction can't get a
        # password.  Possibly it should raise a more specific error but it
        # can't succeed.
        ui = _mod_ui.SilentUIFactory()
        stdout = tests.StringIOWrapper()
        self.assertRaises(
            NotImplementedError,
            self.apply_redirected,
            None, stdout, stdout, ui.get_password)
        # and it didn't write anything out either
        self.assertEqual('', stdout.getvalue())

    def test_silent_ui_getbool(self):
        factory = _mod_ui.SilentUIFactory()
        stdout = tests.StringIOWrapper()
        self.assertRaises(
            NotImplementedError,
            self.apply_redirected,
            None, stdout, stdout, factory.get_boolean, "foo")


class TestUIFactoryTests(tests.TestCase):

    def test_test_ui_factory_progress(self):
        # there's no output; we just want to make sure this doesn't crash -
        # see https://bugs.launchpad.net/bzr/+bug/408201
        ui = tests.TestUIFactory()
        pb = ui.nested_progress_bar()
        pb.update('hello')
        pb.tick()
        pb.finished()


class CannedInputUIFactoryTests(tests.TestCase):

    def test_canned_input_get_input(self):
        uif = _mod_ui.CannedInputUIFactory([True, 'mbp', 'password', 42])
        self.assertEqual(True, uif.get_boolean('Extra cheese?'))
        self.assertEqual('mbp', uif.get_username('Enter your user name'))
        self.assertEqual('password',
                         uif.get_password('Password for %(host)s',
                                          host='example.com'))
        self.assertEqual(42, uif.get_integer('And all that jazz ?'))


class TestBoolFromString(tests.TestCase):

    def assertIsTrue(self, s, accepted_values=None):
        res = _mod_ui.bool_from_string(s, accepted_values=accepted_values)
        self.assertEquals(True, res)

    def assertIsFalse(self, s, accepted_values=None):
        res = _mod_ui.bool_from_string(s, accepted_values=accepted_values)
        self.assertEquals(False, res)

    def assertIsNone(self, s, accepted_values=None):
        res = _mod_ui.bool_from_string(s, accepted_values=accepted_values)
        self.assertIs(None, res)

    def test_know_valid_values(self):
        self.assertIsTrue('true')
        self.assertIsFalse('false')
        self.assertIsTrue('1')
        self.assertIsFalse('0')
        self.assertIsTrue('on')
        self.assertIsFalse('off')
        self.assertIsTrue('yes')
        self.assertIsFalse('no')
        self.assertIsTrue('y')
        self.assertIsFalse('n')
        # Also try some case variations
        self.assertIsTrue('True')
        self.assertIsFalse('False')
        self.assertIsTrue('On')
        self.assertIsFalse('Off')
        self.assertIsTrue('ON')
        self.assertIsFalse('OFF')
        self.assertIsTrue('oN')
        self.assertIsFalse('oFf')

    def test_invalid_values(self):
        self.assertIsNone(None)
        self.assertIsNone('doubt')
        self.assertIsNone('frue')
        self.assertIsNone('talse')
        self.assertIsNone('42')

    def test_provided_values(self):
        av = dict(y=True, n=False, yes=True, no=False)
        self.assertIsTrue('y', av)
        self.assertIsTrue('Y', av)
        self.assertIsTrue('Yes', av)
        self.assertIsFalse('n', av)
        self.assertIsFalse('N', av)
        self.assertIsFalse('No', av)
        self.assertIsNone('1', av)
        self.assertIsNone('0', av)
        self.assertIsNone('on', av)
        self.assertIsNone('off', av)
