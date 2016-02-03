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

"""Tests for the bzrlib ui
"""

import time

from StringIO import StringIO

from testtools.matchers import *

from bzrlib import (
    config,
    remote,
    tests,
    ui as _mod_ui,
    )
from bzrlib.tests import (
    fixtures,
    )
from bzrlib.ui import text as _mod_ui_text
from bzrlib.tests.testui import (
    ProgressRecordingUIFactory,
    )


class TTYStringIO(StringIO):
    """A helper class which makes a StringIO look like a terminal"""

    def isatty(self):
        return True


class NonTTYStringIO(StringIO):
    """Helper that implements isatty() but returns False"""

    def isatty(self):
        return False


class TestUIConfiguration(tests.TestCaseWithTransport):

    def test_output_encoding_configuration(self):
        enc = fixtures.generate_unicode_encodings().next()
        config.GlobalStack().set('output_encoding', enc)
        ui = tests.TestUIFactory(stdin=None,
            stdout=tests.StringIOWrapper(),
            stderr=tests.StringIOWrapper())
        output = ui.make_output_stream()
        self.assertEqual(output.encoding, enc)


class TestTextUIFactory(tests.TestCase):

    def make_test_ui_factory(self, stdin_contents):
        ui = tests.TestUIFactory(stdin=stdin_contents,
                                 stdout=tests.StringIOWrapper(),
                                 stderr=tests.StringIOWrapper())
        return ui

    def test_text_factory_confirm(self):
        # turns into reading a regular boolean
        ui = self.make_test_ui_factory('n\n')
        self.assertEqual(ui.confirm_action(u'Should %(thing)s pass?',
            'bzrlib.tests.test_ui.confirmation',
            {'thing': 'this'},),
            False)

    def test_text_factory_ascii_password(self):
        ui = self.make_test_ui_factory('secret\n')
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
        """Test an utf8 password."""
        ui = _mod_ui_text.TextUIFactory(None, None, None)
        ui.stdin = tests.StringIOWrapper(u'baz\u1234'.encode('utf8'))
        ui.stdout = tests.StringIOWrapper()
        ui.stderr = tests.StringIOWrapper()
        ui.stderr.encoding = ui.stdout.encoding = ui.stdin.encoding = 'utf8'
        password = ui.get_password(u'Hello \u1234 %(user)s', user=u'some\u1234')
        self.assertEqual(u'baz\u1234', password)
        self.assertEqual(u'Hello \u1234 some\u1234: ',
                         ui.stderr.getvalue().decode('utf8'))
        # stdin and stdout should be empty
        self.assertEqual('', ui.stdin.readline())
        self.assertEqual('', ui.stdout.getvalue())

    def test_text_ui_get_boolean(self):
        stdin = tests.StringIOWrapper("y\n" # True
                                      "n\n" # False
                                      " \n y \n" # True
                                      " no \n" # False
                                      "yes with garbage\nY\n" # True
                                      "not an answer\nno\n" # False
                                      "I'm sure!\nyes\n" # True
                                      "NO\n" # False
                                      "foo\n")
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        factory = _mod_ui_text.TextUIFactory(stdin, stdout, stderr)
        self.assertEqual(True, factory.get_boolean(u""))
        self.assertEqual(False, factory.get_boolean(u""))
        self.assertEqual(True, factory.get_boolean(u""))
        self.assertEqual(False, factory.get_boolean(u""))
        self.assertEqual(True, factory.get_boolean(u""))
        self.assertEqual(False, factory.get_boolean(u""))
        self.assertEqual(True, factory.get_boolean(u""))
        self.assertEqual(False, factory.get_boolean(u""))
        self.assertEqual("foo\n", factory.stdin.read())
        # stdin should be empty
        self.assertEqual('', factory.stdin.readline())
        # return false on EOF
        self.assertEqual(False, factory.get_boolean(u""))

    def test_text_ui_choose_bad_parameters(self):
        stdin = tests.StringIOWrapper()
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        factory = _mod_ui_text.TextUIFactory(stdin, stdout, stderr)
        # invalid default index
        self.assertRaises(ValueError, factory.choose, u"", u"&Yes\n&No", 3)
        # duplicated choice
        self.assertRaises(ValueError, factory.choose, u"", u"&choice\n&ChOiCe")
        # duplicated shortcut
        self.assertRaises(ValueError, factory.choose, u"", u"&choice1\nchoi&ce2")

    def test_text_ui_choose_prompt(self):
        stdin = tests.StringIOWrapper()
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        factory = _mod_ui_text.TextUIFactory(stdin, stdout, stderr)
        # choices with explicit shortcuts
        factory.choose(u"prompt", u"&yes\n&No\nmore &info")
        self.assertEqual("prompt ([y]es, [N]o, more [i]nfo): \n", factory.stderr.getvalue())
        # automatic shortcuts
        factory.stderr.truncate(0)
        factory.choose(u"prompt", u"yes\nNo\nmore info")
        self.assertEqual("prompt ([y]es, [N]o, [m]ore info): \n", factory.stderr.getvalue())

    def test_text_ui_choose_return_values(self):
        choose = lambda: factory.choose(u"", u"&Yes\n&No\nMaybe\nmore &info", 3)
        stdin = tests.StringIOWrapper("y\n" # 0
                                      "n\n" # 1
                                      " \n" # default: 3
                                      " no \n" # 1
                                      "b\na\nd \n" # bad shortcuts, all ignored
                                      "yes with garbage\nY\n" # 0
                                      "not an answer\nno\n" # 1
                                      "info\nmore info\n" # 3
                                      "Maybe\n" # 2
                                      "foo\n")
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        factory = _mod_ui_text.TextUIFactory(stdin, stdout, stderr)
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
        self.assertEqual('', factory.stdin.readline())
        # return None on EOF
        self.assertEqual(None, choose())

    def test_text_ui_choose_no_default(self):
        stdin = tests.StringIOWrapper(" \n" # no default, invalid!
                                      " yes \n" # 0
                                      "foo\n")
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        factory = _mod_ui_text.TextUIFactory(stdin, stdout, stderr)
        self.assertEqual(0, factory.choose(u"", u"&Yes\n&No"))
        self.assertEqual("foo\n", factory.stdin.read())

    def test_text_ui_get_integer(self):
        stdin = tests.StringIOWrapper(
            "1\n"
            "  -2  \n"
            "hmmm\nwhat else ?\nCome on\nok 42\n4.24\n42\n")
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        factory = _mod_ui_text.TextUIFactory(stdin, stdout, stderr)
        self.assertEqual(1, factory.get_integer(u""))
        self.assertEqual(-2, factory.get_integer(u""))
        self.assertEqual(42, factory.get_integer(u""))

    def test_text_factory_prompt(self):
        # see <https://launchpad.net/bugs/365891>
        StringIO = tests.StringIOWrapper
        factory = _mod_ui_text.TextUIFactory(StringIO(), StringIO(), StringIO())
        factory.prompt(u'foo %2e')
        self.assertEqual('', factory.stdout.getvalue())
        self.assertEqual('foo %2e', factory.stderr.getvalue())

    def test_text_factory_prompts_and_clears(self):
        # a get_boolean call should clear the pb before prompting
        out = TTYStringIO()
        self.overrideEnv('TERM', 'xterm')
        factory = _mod_ui_text.TextUIFactory(
            stdin=tests.StringIOWrapper("yada\ny\n"),
            stdout=out, stderr=out)
        factory._avail_width = lambda: 79
        pb = factory.nested_progress_bar()
        pb.show_bar = False
        pb.show_spinner = False
        pb.show_count = False
        pb.update("foo", 0, 1)
        self.assertEqual(True,
                         self.apply_redirected(None, factory.stdout,
                                               factory.stdout,
                                               factory.get_boolean,
                                               u"what do you want"))
        output = out.getvalue()
        self.assertContainsRe(output,
            "| foo *\r\r  *\r*")
        self.assertContainsString(output,
            r"what do you want? ([y]es, [n]o): what do you want? ([y]es, [n]o): ")
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
        ui = _mod_ui_text.TextUIFactory(None, None, None)
        ui.stdin = tests.StringIOWrapper('someuser\n\n')
        ui.stdout = tests.StringIOWrapper()
        ui.stderr = tests.StringIOWrapper()
        ui.stdout.encoding = 'utf8'
        self.assertEqual('someuser',
                         ui.get_username(u'Hello %(host)s', host='some'))
        self.assertEqual('Hello some: ', ui.stderr.getvalue())
        self.assertEqual('', ui.stdout.getvalue())
        self.assertEqual('', ui.get_username(u"Gebruiker"))
        # stdin should be empty
        self.assertEqual('', ui.stdin.readline())

    def test_text_ui_getusername_utf8(self):
        ui = _mod_ui_text.TextUIFactory(None, None, None)
        ui.stdin = tests.StringIOWrapper(u'someuser\u1234'.encode('utf8'))
        ui.stdout = tests.StringIOWrapper()
        ui.stderr = tests.StringIOWrapper()
        ui.stderr.encoding = ui.stdout.encoding = ui.stdin.encoding = "utf8"
        username = ui.get_username(u'Hello %(host)s', host=u'some\u1234')
        self.assertEqual(u"someuser\u1234", username)
        self.assertEqual(u"Hello some\u1234: ",
                          ui.stderr.getvalue().decode("utf8"))
        self.assertEqual('', ui.stdout.getvalue())

    def test_quietness(self):
        self.overrideEnv('BZR_PROGRESS_BAR', 'text')
        ui_factory = _mod_ui_text.TextUIFactory(None,
            TTYStringIO(),
            TTYStringIO())
        self.assertIsInstance(ui_factory._progress_view,
            _mod_ui_text.TextProgressView)
        ui_factory.be_quiet(True)
        self.assertIsInstance(ui_factory._progress_view,
            _mod_ui_text.NullProgressView)

    def test_text_ui_show_user_warning(self):
        from bzrlib.repofmt.groupcompress_repo import RepositoryFormat2a
        from bzrlib.repofmt.knitpack_repo import RepositoryFormatKnitPack5
        err = StringIO()
        out = StringIO()
        ui = tests.TextUIFactory(stdin=None, stdout=out, stderr=err)
        remote_fmt = remote.RemoteRepositoryFormat()
        remote_fmt._network_name = RepositoryFormatKnitPack5().network_name()
        ui.show_user_warning('cross_format_fetch', from_format=RepositoryFormat2a(),
            to_format=remote_fmt)
        self.assertEqual('', out.getvalue())
        self.assertEqual("Doing on-the-fly conversion from RepositoryFormat2a() to "
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
        self.assertEqual('', out.getvalue())
        self.assertEqual('', err.getvalue())


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
            self.overrideEnv('TERM', term)
            self.overrideEnv('BZR_PROGRESS_BAR', pb)
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
        stdin = NonTTYStringIO('')
        stderr = NonTTYStringIO()
        stdout = NonTTYStringIO()
        for term_type in ['dumb', None, 'xterm']:
            self.overrideEnv('TERM', term_type)
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
            None, stdout, stdout, factory.get_boolean, u"foo")


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
        self.assertEqual(True, uif.get_boolean(u'Extra cheese?'))
        self.assertEqual('mbp', uif.get_username(u'Enter your user name'))
        self.assertEqual('password',
                         uif.get_password(u'Password for %(host)s',
                                          host='example.com'))
        self.assertEqual(42, uif.get_integer(u'And all that jazz ?'))


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


class TestConfirmationUserInterfacePolicy(tests.TestCase):

    def test_confirm_action_default(self):
        base_ui = _mod_ui.NoninteractiveUIFactory()
        for answer in [True, False]:
            self.assertEqual(
                _mod_ui.ConfirmationUserInterfacePolicy(base_ui, answer, {})
                .confirm_action("Do something?",
                    "bzrlib.tests.do_something", {}),
                answer)

    def test_confirm_action_specific(self):
        base_ui = _mod_ui.NoninteractiveUIFactory()
        for default_answer in [True, False]:
            for specific_answer in [True, False]:
                for conf_id in ['given_id', 'other_id']:
                    wrapper = _mod_ui.ConfirmationUserInterfacePolicy(
                        base_ui, default_answer, dict(given_id=specific_answer))
                    result = wrapper.confirm_action("Do something?", conf_id, {})
                    if conf_id == 'given_id':
                        self.assertEqual(result, specific_answer)
                    else:
                        self.assertEqual(result, default_answer)

    def test_repr(self):
        base_ui = _mod_ui.NoninteractiveUIFactory()
        wrapper = _mod_ui.ConfirmationUserInterfacePolicy(
            base_ui, True, dict(a=2))
        self.assertThat(repr(wrapper),
            Equals("ConfirmationUserInterfacePolicy("
                "NoninteractiveUIFactory(), True, {'a': 2})"))


class TestProgressRecordingUI(tests.TestCase):
    """Test test-oriented UIFactory that records progress updates"""

    def test_nested_ignore_depth_beyond_one(self):
        # we only want to capture the first level out progress, not
        # want sub-components might do. So we have nested bars ignored.
        factory = ProgressRecordingUIFactory()
        pb1 = factory.nested_progress_bar()
        pb1.update('foo', 0, 1)
        pb2 = factory.nested_progress_bar()
        pb2.update('foo', 0, 1)
        pb2.finished()
        pb1.finished()
        self.assertEqual([("update", 0, 1, 'foo')], factory._calls)
