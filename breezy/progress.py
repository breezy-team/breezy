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

__docformat__ = "google"

"""Progress indicators.

The usual way to use this is via breezy.ui.ui_factory.nested_progress_bar which
will manage a conceptual stack of nested activities.
"""

import time
import os


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

    The message given when updating a task must be unicode, not bytes.

    Attributes:
      update_latency: The interval (in seconds) at which the PB should be
        updated.  Setting this to zero suggests every update should be shown
        synchronously.

      show_transport_activity: If true (default), transport activity
        will be shown when this task is drawn.  Disable it if you're sure
        that only irrelevant or uninteresting transport activity can occur
        during this task.
    """

    def __init__(self, parent_task=None, ui_factory=None, progress_view=None):
        """Construct a new progress task.

        Args:
          parent_task: Enclosing ProgressTask or None.
          progress_view: ProgressView to display this ProgressTask.
          ui_factory: The UI factory that will display updates;
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
        """Report updated task message and if relevent progress counters

        The message given must be unicode, not a byte string.
        """
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
            own_fraction = (float(self.current_cnt) +
                            child_fraction) / self.total_cnt
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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finished()
        return False


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

    def child_progress(self, **kwargs):
        return DummyProgress(**kwargs)


def str_tdelta(delt):
    if delt is None:
        return "-:--:--"
    delt = int(round(delt))
    return '%d:%02d:%02d' % (delt / 3600,
                             (delt / 60) % 60,
                             delt % 60)


def get_eta(start_time, current, total, enough_samples=3, last_updates=None,
            n_recent=10):
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
