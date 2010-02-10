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


"""Progress indicators.

The usual way to use this is via bzrlib.ui.ui_factory.nested_progress_bar which
will manage a conceptual stack of nested activities.
"""


import sys
import time
import os


from bzrlib import (
    errors,
    )
from bzrlib.trace import mutter
from bzrlib.symbol_versioning import (
    deprecated_function,
    deprecated_in,
    deprecated_method,
    )


def _supports_progress(f):
    """Detect if we can use pretty progress bars on file F.

    If this returns true we expect that a human may be looking at that
    output, and that we can repaint a line to update it.

    This doesn't check the policy for whether we *should* use them.
    """
    isatty = getattr(f, 'isatty', None)
    if isatty is None:
        return False
    if not isatty():
        return False
    # The following case also handles Win32 - on that platform $TERM is
    # typically never set, so the case None is treated as a smart terminal,
    # not dumb.  <https://bugs.launchpad.net/bugs/334808>  win32 files do have
    # isatty methods that return true.
    if os.environ.get('TERM') == 'dumb':
        # e.g. emacs compile window
        return False
    return True


class ProgressTask(object):
    """Model component of a progress indicator.

    Most code that needs to indicate progress should update one of these,
    and it will in turn update the display, if one is present.

    Code updating the task may also set fields as hints about how to display
    it: show_pct, show_spinner, show_eta, show_count, show_bar.  UIs
    will not necessarily respect all these fields.
    
    :ivar update_latency: The interval (in seconds) at which the PB should be
        updated.  Setting this to zero suggests every update should be shown
        synchronously.

    :ivar show_transport_activity: If true (default), transport activity
        will be shown when this task is drawn.  Disable it if you're sure 
        that only irrelevant or uninteresting transport activity can occur
        during this task.
    """

    def __init__(self, parent_task=None, ui_factory=None, progress_view=None):
        """Construct a new progress task.

        :param parent_task: Enclosing ProgressTask or None.

        :param progress_view: ProgressView to display this ProgressTask.

        :param ui_factory: The UI factory that will display updates; 
            deprecated in favor of passing progress_view directly.

        Normally you should not call this directly but rather through
        `ui_factory.nested_progress_bar`.
        """
        self._parent_task = parent_task
        self._last_update = 0
        self.total_cnt = None
        self.current_cnt = None
        self.msg = ''
        # TODO: deprecate passing ui_factory
        self.ui_factory = ui_factory
        self.progress_view = progress_view
        self.show_pct = False
        self.show_spinner = True
        self.show_eta = False,
        self.show_count = True
        self.show_bar = True
        self.update_latency = 0.1
        self.show_transport_activity = True

    def __repr__(self):
        return '%s(%r/%r, msg=%r)' % (
            self.__class__.__name__,
            self.current_cnt,
            self.total_cnt,
            self.msg)

    def update(self, msg, current_cnt=None, total_cnt=None):
        self.msg = msg
        self.current_cnt = current_cnt
        if total_cnt:
            self.total_cnt = total_cnt
        if self.progress_view:
            self.progress_view.show_progress(self)
        else:
            self.ui_factory._progress_updated(self)

    def tick(self):
        self.update(self.msg)

    def finished(self):
        if self.progress_view:
            self.progress_view.task_finished(self)
        else:
            self.ui_factory._progress_finished(self)

    def make_sub_task(self):
        return ProgressTask(self, ui_factory=self.ui_factory,
            progress_view=self.progress_view)

    def _overall_completion_fraction(self, child_fraction=0.0):
        """Return fractional completion of this task and its parents

        Returns None if no completion can be computed."""
        if self.current_cnt is not None and self.total_cnt:
            own_fraction = (float(self.current_cnt) + child_fraction) / self.total_cnt
        else:
            # if this task has no estimation, it just passes on directly
            # whatever the child has measured...
            own_fraction = child_fraction
        if self._parent_task is None:
            return own_fraction
        else:
            if own_fraction is None:
                own_fraction = 0.0
            return self._parent_task._overall_completion_fraction(own_fraction)

    @deprecated_method(deprecated_in((2, 1, 0)))
    def note(self, fmt_string, *args):
        """Record a note without disrupting the progress bar.
        
        Deprecated: use ui_factory.note() instead or bzrlib.trace.  Note that
        ui_factory.note takes just one string as the argument, not a format
        string and arguments.
        """
        if args:
            self.ui_factory.note(fmt_string % args)
        else:
            self.ui_factory.note(fmt_string)

    def clear(self):
        # TODO: deprecate this method; the model object shouldn't be concerned
        # with whether it's shown or not.  Most callers use this because they
        # want to write some different non-progress output to the screen, but
        # they should probably instead use a stream that's synchronized with
        # the progress output.  It may be there is a model-level use for
        # saying "this task's not active at the moment" but I don't see it. --
        # mbp 20090623
        if self.progress_view:
            self.progress_view.clear()
        else:
            self.ui_factory.clear_term()


# NOTE: This is also deprecated; you should provide a ProgressView instead.
class _BaseProgressBar(object):

    def __init__(self,
                 to_file=None,
                 show_pct=False,
                 show_spinner=False,
                 show_eta=False,
                 show_bar=True,
                 show_count=True,
                 to_messages_file=None,
                 _stack=None):
        object.__init__(self)
        if to_file is None:
            to_file = sys.stderr
        if to_messages_file is None:
            to_messages_file = sys.stdout
        self.to_file = to_file
        self.to_messages_file = to_messages_file
        self.last_msg = None
        self.last_cnt = None
        self.last_total = None
        self.show_pct = show_pct
        self.show_spinner = show_spinner
        self.show_eta = show_eta
        self.show_bar = show_bar
        self.show_count = show_count
        self._stack = _stack
        # seed throttler
        self.MIN_PAUSE = 0.1 # seconds
        now = time.time()
        # starting now
        self.start_time = now
        # next update should not throttle
        self.last_update = now - self.MIN_PAUSE - 1

    def finished(self):
        """Return this bar to its progress stack."""
        self.clear()
        self._stack.return_pb(self)

    def note(self, fmt_string, *args, **kwargs):
        """Record a note without disrupting the progress bar."""
        self.clear()
        self.to_messages_file.write(fmt_string % args)
        self.to_messages_file.write('\n')


class DummyProgress(object):
    """Progress-bar standin that does nothing.

    This was previously often constructed by application code if no progress
    bar was explicitly passed in.  That's no longer recommended: instead, just
    create a progress task from the ui_factory.  This class can be used in
    test code that needs to fake a progress task for some reason.
    """

    def tick(self):
        pass

    def update(self, msg=None, current=None, total=None):
        pass

    def child_update(self, message, current, total):
        pass

    def clear(self):
        pass

    def note(self, fmt_string, *args, **kwargs):
        """See _BaseProgressBar.note()."""

    def child_progress(self, **kwargs):
        return DummyProgress(**kwargs)


def str_tdelta(delt):
    if delt is None:
        return "-:--:--"
    delt = int(round(delt))
    return '%d:%02d:%02d' % (delt/3600,
                             (delt/60) % 60,
                             delt % 60)


def get_eta(start_time, current, total, enough_samples=3, last_updates=None, n_recent=10):
    if start_time is None:
        return None

    if not total:
        return None

    if current < enough_samples:
        return None

    if current > total:
        return None                     # wtf?

    elapsed = time.time() - start_time

    if elapsed < 2.0:                   # not enough time to estimate
        return None

    total_duration = float(elapsed) * float(total) / float(current)

    if last_updates and len(last_updates) >= n_recent:
        avg = sum(last_updates) / float(len(last_updates))
        time_left = avg * (total - current)

        old_time_left = total_duration - elapsed

        # We could return the average, or some other value here
        return (time_left + old_time_left) / 2

    return total_duration - elapsed


class ProgressPhase(object):
    """Update progress object with the current phase"""
    def __init__(self, message, total, pb):
        object.__init__(self)
        self.pb = pb
        self.message = message
        self.total = total
        self.cur_phase = None

    def next_phase(self):
        if self.cur_phase is None:
            self.cur_phase = 0
        else:
            self.cur_phase += 1
        self.pb.update(self.message, self.cur_phase, self.total)


_progress_bar_types = {}
_progress_bar_types['dummy'] = DummyProgress
_progress_bar_types['none'] = DummyProgress
