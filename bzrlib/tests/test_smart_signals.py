# Copyright (C) 2011 Canonical Ltd
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


import signal
import weakref

from bzrlib import tests
from bzrlib.smart import signals


class TestSignalHandlers(tests.TestCase):

    def setUp(self):
        super(TestSignalHandlers, self).setUp()
        # This allows us to mutate the signal handler callbacks, but leave it
        # 'pristine' after the test case.
        # TODO: Arguably, this could be put into the base test.TestCase, along
        #       with a tearDown that asserts that all the entries have been
        #       removed properly. Global state is always a bit messy. A shame
        #       that we need it for signal handling.
        orig = signals._setup_on_hangup_dict()
        self.assertIs(None, orig)
        def cleanup():
            signals._on_sighup = None
        self.addCleanup(cleanup)

    def test_registered_callback_gets_called(self):
        calls = []
        def call_me():
            calls.append('called')
        signals.register_on_hangup('myid', call_me)
        signals._sighup_handler(signal.SIGHUP, None)
        self.assertEqual(['called'], calls)
        signals.unregister_on_hangup('myid')

    def test_unregister_not_present(self):
        # We don't want unregister to fail, since it is generally run at times
        # that shouldn't interrupt other flow.
        signals.unregister_on_hangup('no-such-id')
        log = self.get_log()
        self.assertContainsRe(log, 'Error occurred during unregister_on_hangup:')
        self.assertContainsRe(log, '(?s)Traceback.*KeyError')

    def test_failing_callback(self):
        calls = []
        def call_me():
            calls.append('called')
        def fail_me():
            raise RuntimeError('something bad happened')
        signals.register_on_hangup('myid', call_me)
        signals.register_on_hangup('otherid', fail_me)
        # _sighup_handler should call both, even though it got an exception
        signals._sighup_handler(signal.SIGHUP, None)
        signals.unregister_on_hangup('myid')
        signals.unregister_on_hangup('otherid')
        log = self.get_log()
        self.assertContainsRe(log, '(?s)Traceback.*RuntimeError')
        self.assertEqual(['called'], calls)

    def test_unregister_during_call(self):
        # _sighup_handler should handle if some callbacks actually remove
        # themselves while running.
        calls = []
        def call_me_and_unregister():
            signals.unregister_on_hangup('myid')
            calls.append('called_and_unregistered')
        def call_me():
            calls.append('called')
        signals.register_on_hangup('myid', call_me_and_unregister)
        signals.register_on_hangup('other', call_me)
        signals._sighup_handler(signal.SIGHUP, None)

    def test_keyboard_interrupt_propagated(self):
        # In case we get 'stuck' while running a hangup function, we should
        # not suppress KeyboardInterrupt
        def call_me_and_raise():
            raise KeyboardInterrupt()
        signals.register_on_hangup('myid', call_me_and_raise)
        self.assertRaises(KeyboardInterrupt,
                          signals._sighup_handler, signal.SIGHUP, None)
        signals.unregister_on_hangup('myid')

    def test_weak_references(self):
        # TODO: This is probably a very-CPython-specific test
        # Adding yourself to the callback should not make you immortal
        # We overrideAttr during the test suite, so that we don't pollute the
        # original dict. However, we can test that what we override matches
        # what we are putting there.
        self.assertIsInstance(signals._on_sighup,
                              weakref.WeakValueDictionary)
        calls = []
        def call_me():
            calls.append('called')
        signals.register_on_hangup('myid', call_me)
        del call_me
        # Non-CPython might want to do a gc.collect() here
        signals._sighup_handler(signal.SIGHUP, None)
        self.assertEqual([], calls)

    def test_not_installed(self):
        # If you haven't called bzrlib.smart.signals.install_sighup_handler,
        # then _on_sighup should be None, and all the calls become no-ops.
        signals._on_sighup = None
        calls = []
        def call_me():
            calls.append('called')
        signals.register_on_hangup('myid', calls)
        signals._sighup_handler(signal.SIGHUP, None)
        signals.unregister_on_hangup('myid')
        log = self.get_log()
        self.assertEqual('', log)
