# Copyright (C) 2006 Canonical Ltd
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

import os
from StringIO import StringIO

from bzrlib import errors
from bzrlib.progress import (
        DummyProgress, ChildProgress,
        TTYProgressBar,
        DotsProgressBar,
        ProgressBarStack,
        )
from bzrlib.tests import TestCase


class FakeStack:
    def __init__(self, top):
        self.__top = top

    def top(self):
        return self.__top

class InstrumentedProgress(TTYProgressBar):
    """TTYProgress variant that tracks outcomes"""

    def __init__(self, *args, **kwargs):
        self.always_throttled = True
        TTYProgressBar.__init__(self, *args, **kwargs)

    def throttle(self, old_message):
        result = TTYProgressBar.throttle(self, old_message)
        if result is False:
            self.always_throttled = False
        

class _TTYStringIO(StringIO):
    """A helper class which makes a StringIO look like a terminal"""

    def isatty(self):
        return True


class _NonTTYStringIO(StringIO):
    """Helper that implements isatty() but returns False"""

    def isatty(self):
        return False


class TestProgress(TestCase):
    def setUp(self):
        q = DummyProgress()
        self.top = ChildProgress(_stack=FakeStack(q))

    def test_propogation(self):
        self.top.update('foobles', 1, 2)
        self.assertEqual(self.top.message, 'foobles')
        self.assertEqual(self.top.current, 1)
        self.assertEqual(self.top.total, 2)
        self.assertEqual(self.top.child_fraction, 0)
        child = ChildProgress(_stack=FakeStack(self.top))
        child.update('baubles', 2, 4)
        self.assertEqual(self.top.message, 'foobles')
        self.assertEqual(self.top.current, 1)
        self.assertEqual(self.top.total, 2)
        self.assertEqual(self.top.child_fraction, 0.5)
        grandchild = ChildProgress(_stack=FakeStack(child))
        grandchild.update('barbells', 1, 2)
        self.assertEqual(self.top.child_fraction, 0.625)
        self.assertEqual(child.child_fraction, 0.5)
        child.update('baubles', 3, 4)
        self.assertEqual(child.child_fraction, 0)
        self.assertEqual(self.top.child_fraction, 0.75)
        grandchild.update('barbells', 1, 2)
        self.assertEqual(self.top.child_fraction, 0.875)
        grandchild.update('barbells', 2, 2)
        self.assertEqual(self.top.child_fraction, 1)
        child.update('baubles', 4, 4)
        self.assertEqual(self.top.child_fraction, 1)
        #test clamping
        grandchild.update('barbells', 2, 2)
        self.assertEqual(self.top.child_fraction, 1)

    def test_implementations(self):
        for implementation in (TTYProgressBar, DotsProgressBar, 
                               DummyProgress):
            self.check_parent_handling(implementation)

    def check_parent_handling(self, parentclass):
        top = parentclass(to_file=StringIO())
        top.update('foobles', 1, 2)
        child = ChildProgress(_stack=FakeStack(top))
        child.update('baubles', 4, 4)
        top.update('lala', 2, 2)
        child.update('baubles', 4, 4)

    def test_stacking(self):
        self.check_stack(TTYProgressBar, ChildProgress)
        self.check_stack(DotsProgressBar, ChildProgress)
        self.check_stack(DummyProgress, DummyProgress)

    def check_stack(self, parent_class, child_class):
        stack = ProgressBarStack(klass=parent_class, to_file=StringIO())
        parent = stack.get_nested()
        try:
            self.assertIs(parent.__class__, parent_class)
            child = stack.get_nested()
            try:
                self.assertIs(child.__class__, child_class)
            finally:
                child.finished()
        finally:
            parent.finished()

    def test_throttling(self):
        pb = InstrumentedProgress(to_file=StringIO())
        # instantaneous updates should be squelched
        pb.update('me', 1, 1)
        self.assertTrue(pb.always_throttled)
        pb = InstrumentedProgress(to_file=StringIO())
        # It's like an instant sleep(1)!
        pb.start_time -= 1
        # Updates after a second should not be squelched
        pb.update('me', 1, 1)
        self.assertFalse(pb.always_throttled)

    def test_clear(self):
        sio = StringIO()
        pb = TTYProgressBar(to_file=sio, show_eta=False)
        pb.width = 20 # Just make it easier to test
        # This should not output anything
        pb.clear()
        # These two should not be displayed because
        # of throttling
        pb.update('foo', 1, 3)
        pb.update('bar', 2, 3)
        # So pb.clear() has nothing to do
        pb.clear()

        # Make sure the next update isn't throttled
        pb.start_time -= 1
        pb.update('baz', 3, 3)
        pb.clear()

        self.assertEqual('\r[=========] baz 3/3'
                         '\r                   \r',
                         sio.getvalue())

    def test_no_eta(self):
        # An old version of the progress bar would
        # store every update if show_eta was false
        # because the eta routine was where it was
        # cleaned out
        pb = InstrumentedProgress(to_file=StringIO(), show_eta=False)
        # Just make sure this first few are throttled
        pb.start_time += 5

        # These messages are throttled, and don't contribute
        for count in xrange(100):
            pb.update('x', count, 300)
        self.assertEqual(0, len(pb.last_updates))

        # Unthrottle by time
        pb.start_time -= 10

        # These happen too fast, so only one gets through
        for count in xrange(100):
            pb.update('x', count+100, 200)
        self.assertEqual(1, len(pb.last_updates))

        pb.MIN_PAUSE = 0.0

        # But all of these go through, don't let the
        # last_update list grow without bound
        for count in xrange(100):
            pb.update('x', count+100, 200)

        self.assertEqual(pb._max_last_updates, len(pb.last_updates))


class TestProgressTypes(TestCase):
    """Test that the right ProgressBar gets instantiated at the right time."""

    def get_nested(self, outf, term, env_progress=None):
        """Setup so that ProgressBar thinks we are in the supplied terminal."""
        orig_term = os.environ.get('TERM')
        orig_progress = os.environ.get('BZR_PROGRESS_BAR')
        os.environ['TERM'] = term
        if env_progress is not None:
            os.environ['BZR_PROGRESS_BAR'] = env_progress
        elif orig_progress is not None:
            del os.environ['BZR_PROGRESS_BAR']

        def reset():
            if orig_term is None:
                del os.environ['TERM']
            else:
                os.environ['TERM'] = orig_term
            # We may have never created BZR_PROGRESS_BAR
            # So we can't just delete like we can 'TERM' (which is always set)
            if orig_progress is None:
                if 'BZR_PROGRESS_BAR' in os.environ:
                    del os.environ['BZR_PROGRESS_BAR']
            else:
                os.environ['BZR_PROGRESS_BAR'] = orig_progress

        self.addCleanup(reset)

        stack = ProgressBarStack(to_file=outf)
        pb = stack.get_nested()
        pb.start_time -= 1 # Make sure it is ready to write
        pb.width = 20 # And it is of reasonable size
        return pb

    def test_tty_progress(self):
        # Make sure the ProgressBarStack thinks it is
        # writing out to a terminal, and thus uses a TTYProgressBar
        out = _TTYStringIO()
        pb = self.get_nested(out, 'xterm')
        self.assertIsInstance(pb, TTYProgressBar)
        try:
            pb.update('foo', 1, 2)
            pb.update('bar', 2, 2)
        finally:
            pb.finished()

        self.assertEqual('\r/ [====   ] foo 1/2'
                         '\r- [=======] bar 2/2'
                         '\r                   \r',
                         out.getvalue())

    def test_dots_progress(self):
        # Make sure the ProgressBarStack thinks it is
        # not writing out to a terminal, and thus uses a 
        # DotsProgressBar
        out = _NonTTYStringIO()
        pb = self.get_nested(out, 'xterm')
        self.assertIsInstance(pb, DotsProgressBar)
        try:
            pb.update('foo', 1, 2)
            pb.update('bar', 2, 2)
        finally:
            pb.finished()

        self.assertEqual('foo: .'
                         '\nbar: .'
                         '\n',
                         out.getvalue())

    def test_no_isatty_progress(self):
        # Make sure ProgressBarStack handles a plain StringIO()
        import cStringIO
        out = cStringIO.StringIO()
        pb = self.get_nested(out, 'xterm')
        pb.finished()
        self.assertIsInstance(pb, DotsProgressBar)

    def test_dumb_progress(self):
        # Make sure the ProgressBarStack thinks it is writing out to a 
        # terminal, but it is the emacs 'dumb' terminal, so it uses
        # Dots
        out = _TTYStringIO()
        pb = self.get_nested(out, 'dumb')
        pb.finished()
        self.assertIsInstance(pb, DotsProgressBar)

    def test_progress_env_tty(self):
        # The environ variable BZR_PROGRESS_BAR controls what type of
        # progress bar we will get, even if it wouldn't usually be that type
        import cStringIO

        # Usually, this would be a DotsProgressBar
        out = cStringIO.StringIO()
        pb = self.get_nested(out, 'dumb', 'tty')
        pb.finished()
        # Even though we are not a tty, the env_var will override
        self.assertIsInstance(pb, TTYProgressBar)

    def test_progress_env_dots(self):
        # Even though we are in a tty, the env_var will override
        out = _TTYStringIO()
        pb = self.get_nested(out, 'xterm', 'dots')
        pb.finished()
        self.assertIsInstance(pb, DotsProgressBar)

    def test_progress_env_none(self):
        # Even though we are in a valid tty, no progress
        out = _TTYStringIO()
        pb = self.get_nested(out, 'xterm', 'none')
        pb.finished()
        self.assertIsInstance(pb, DummyProgress)

    def test_progress_env_invalid(self):
        out = _TTYStringIO()
        self.assertRaises(errors.InvalidProgressBarType, self.get_nested,
            out, 'xterm', 'nonexistant')
