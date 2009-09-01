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


"""Text UI, write output to the console.
"""

import getpass
import os
import sys
import time
import warnings

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    debug,
    progress,
    osutils,
    symbol_versioning,
    )

""")

from bzrlib.ui import (
    UIFactory,
    NullProgressView,
    )


class TextUIFactory(UIFactory):
    """A UI factory for Text user interefaces."""

    def __init__(self,
                 stdin=None,
                 stdout=None,
                 stderr=None):
        """Create a TextUIFactory.

        :param bar_type: The type of progress bar to create.  Deprecated
            and ignored; a TextProgressView is always used.
        """
        super(TextUIFactory, self).__init__()
        # TODO: there's no good reason not to pass all three streams, maybe we
        # should deprecate the default values...
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        # paints progress, network activity, etc
        self._progress_view = self.make_progress_view()
        
    def clear_term(self):
        """Prepare the terminal for output.

        This will, clear any progress bars, and leave the cursor at the
        leftmost position."""
        # XXX: If this is preparing to write to stdout, but that's for example
        # directed into a file rather than to the terminal, and the progress
        # bar _is_ going to the terminal, we shouldn't need
        # to clear it.  We might need to separately check for the case of
        self._progress_view.clear()

    def get_boolean(self, prompt):
        while True:
            self.prompt(prompt + "? [y/n]: ")
            line = self.stdin.readline().lower()
            if line in ('y\n', 'yes\n'):
                return True
            elif line in ('n\n', 'no\n'):
                return False
            elif line in ('', None):
                # end-of-file; possibly should raise an error here instead
                return None

    def get_non_echoed_password(self):
        isatty = getattr(self.stdin, 'isatty', None)
        if isatty is not None and isatty():
            # getpass() ensure the password is not echoed and other
            # cross-platform niceties
            password = getpass.getpass('')
        else:
            # echo doesn't make sense without a terminal
            password = self.stdin.readline()
            if not password:
                password = None
            elif password[-1] == '\n':
                password = password[:-1]
        return password

    def get_password(self, prompt='', **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.
        :return: The password string, return None if the user
                 canceled the request.
        """
        prompt += ': '
        self.prompt(prompt, **kwargs)
        # There's currently no way to say 'i decline to enter a password'
        # as opposed to 'my password is empty' -- does it matter?
        return self.get_non_echoed_password()

    def get_username(self, prompt, **kwargs):
        """Prompt the user for a username.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.
        :return: The username string, return None if the user
                 canceled the request.
        """
        prompt += ': '
        self.prompt(prompt, **kwargs)
        username = self.stdin.readline()
        if not username:
            username = None
        elif username[-1] == '\n':
            username = username[:-1]
        return username

    def make_progress_view(self):
        """Construct and return a new ProgressView subclass for this UI.
        """
        # if the user specifically requests either text or no progress bars,
        # always do that.  otherwise, guess based on $TERM and tty presence.
        if os.environ.get('BZR_PROGRESS_BAR') == 'text':
            return TextProgressView(self.stderr)
        elif os.environ.get('BZR_PROGRESS_BAR') == 'none':
            return NullProgressView()
        elif progress._supports_progress(self.stderr):
            return TextProgressView(self.stderr)
        else:
            return NullProgressView()

    def note(self, msg):
        """Write an already-formatted message, clearing the progress bar if necessary."""
        self.clear_term()
        self.stdout.write(msg + '\n')

    def prompt(self, prompt, **kwargs):
        """Emit prompt on the CLI.
        
        :param kwargs: Dictionary of arguments to insert into the prompt,
            to allow UIs to reformat the prompt.
        """
        if kwargs:
            # See <https://launchpad.net/bugs/365891>
            prompt = prompt % kwargs
        prompt = prompt.encode(osutils.get_terminal_encoding(), 'replace')
        self.clear_term()
        self.stderr.write(prompt)

    def report_transport_activity(self, transport, byte_count, direction):
        """Called by transports as they do IO.

        This may update a progress bar, spinner, or similar display.
        By default it does nothing.
        """
        self._progress_view.show_transport_activity(transport,
            direction, byte_count)

    def _progress_updated(self, task):
        """A task has been updated and wants to be displayed.
        """
        if not self._task_stack:
            warnings.warn("%r updated but no tasks are active" %
                (task,))
        elif task != self._task_stack[-1]:
            warnings.warn("%r is not the top progress task %r" %
                (task, self._task_stack[-1]))
        self._progress_view.show_progress(task)

    def _progress_all_finished(self):
        self._progress_view.clear()


class TextProgressView(object):
    """Display of progress bar and other information on a tty.

    This shows one line of text, including possibly a network indicator, spinner,
    progress bar, message, etc.

    One instance of this is created and held by the UI, and fed updates when a
    task wants to be painted.

    Transports feed data to this through the ui_factory object.

    The Progress views can comprise a tree with _parent_task pointers, but
    this only prints the stack from the nominated current task up to the root.
    """

    def __init__(self, term_file):
        self._term_file = term_file
        # true when there's output on the screen we may need to clear
        self._have_output = False
        # XXX: We could listen for SIGWINCH and update the terminal width...
        # https://launchpad.net/bugs/316357
        self._width = osutils.terminal_width()
        self._last_transport_msg = ''
        self._spin_pos = 0
        # time we last repainted the screen
        self._last_repaint = 0
        # time we last got information about transport activity
        self._transport_update_time = 0
        self._last_task = None
        self._total_byte_count = 0
        self._bytes_since_update = 0
        self._fraction = 0

    def _show_line(self, s):
        # sys.stderr.write("progress %r\n" % s)
        n = self._width - 1
        self._term_file.write('\r%-*.*s\r' % (n, n, s))

    def clear(self):
        if self._have_output:
            self._show_line('')
        self._have_output = False

    def _render_bar(self):
        # return a string for the progress bar itself
        if (self._last_task is None) or self._last_task.show_bar:
            # If there's no task object, we show space for the bar anyhow.
            # That's because most invocations of bzr will end showing progress
            # at some point, though perhaps only after doing some initial IO.
            # It looks better to draw the progress bar initially rather than
            # to have what looks like an incomplete progress bar.
            spin_str =  r'/-\|'[self._spin_pos % 4]
            self._spin_pos += 1
            cols = 20
            if self._last_task is None:
                completion_fraction = 0
                self._fraction = 0
            else:
                completion_fraction = \
                    self._last_task._overall_completion_fraction() or 0
            if (completion_fraction < self._fraction and 'progress' in
                debug.debug_flags):
                import pdb;pdb.set_trace()
            self._fraction = completion_fraction
            markers = int(round(float(cols) * completion_fraction)) - 1
            bar_str = '[' + ('#' * markers + spin_str).ljust(cols) + '] '
            return bar_str
        elif self._last_task.show_spinner:
            # The last task wanted just a spinner, no bar
            spin_str =  r'/-\|'[self._spin_pos % 4]
            self._spin_pos += 1
            return spin_str + ' '
        else:
            return ''

    def _format_task(self, task):
        if not task.show_count:
            s = ''
        elif task.current_cnt is not None and task.total_cnt is not None:
            s = ' %d/%d' % (task.current_cnt, task.total_cnt)
        elif task.current_cnt is not None:
            s = ' %d' % (task.current_cnt)
        else:
            s = ''
        # compose all the parent messages
        t = task
        m = task.msg
        while t._parent_task:
            t = t._parent_task
            if t.msg:
                m = t.msg + ':' + m
        return m + s

    def _render_line(self):
        bar_string = self._render_bar()
        if self._last_task:
            task_msg = self._format_task(self._last_task)
        else:
            task_msg = ''
        if self._last_task and not self._last_task.show_transport_activity:
            trans = ''
        else:
            trans = self._last_transport_msg
            if trans:
                trans += ' | '
        return (bar_string + trans + task_msg)

    def _repaint(self):
        s = self._render_line()
        self._show_line(s)
        self._have_output = True

    def show_progress(self, task):
        """Called by the task object when it has changed.
        
        :param task: The top task object; its parents are also included 
            by following links.
        """
        must_update = task is not self._last_task
        self._last_task = task
        now = time.time()
        if (not must_update) and (now < self._last_repaint + task.update_latency):
            return
        if now > self._transport_update_time + 10:
            # no recent activity; expire it
            self._last_transport_msg = ''
        self._last_repaint = now
        self._repaint()

    def show_transport_activity(self, transport, direction, byte_count):
        """Called by transports via the ui_factory, as they do IO.

        This may update a progress bar, spinner, or similar display.
        By default it does nothing.
        """
        # XXX: Probably there should be a transport activity model, and that
        # too should be seen by the progress view, rather than being poked in
        # here.
        if not self._have_output:
            # As a workaround for <https://launchpad.net/bugs/321935> we only
            # show transport activity when there's already a progress bar
            # shown, which time the application code is expected to know to
            # clear off the progress bar when it's going to send some other
            # output.  Eventually it would be nice to have that automatically
            # synchronized.
            return
        self._total_byte_count += byte_count
        self._bytes_since_update += byte_count
        now = time.time()
        if self._total_byte_count < 2000:
            # a little resistance at first, so it doesn't stay stuck at 0
            # while connecting...
            return
        if self._transport_update_time is None:
            self._transport_update_time = now
        elif now >= (self._transport_update_time + 0.5):
            # guard against clock stepping backwards, and don't update too
            # often
            rate = self._bytes_since_update / (now - self._transport_update_time)
            msg = ("%6dKB %5dKB/s" %
                    (self._total_byte_count>>10, int(rate)>>10,))
            self._transport_update_time = now
            self._last_repaint = now
            self._bytes_since_update = 0
            self._last_transport_msg = msg
            self._repaint()
