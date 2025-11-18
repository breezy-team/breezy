# Copyright (C) 2005-2011 Canonical Ltd
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

"""Text UI, write output to the console."""

import codecs
import io
import os
import sys
import warnings

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
import time

from breezy import (
    debug,
    progress,
    )
""",
)

from .. import config, osutils, trace
from . import NullProgressView, UIFactory


class _ChooseUI:
    """Helper class for choose implementation."""

    def __init__(self, ui, msg, choices, default):
        self.ui = ui
        self._setup_mode()
        self._build_alternatives(msg, choices, default)

    def _setup_mode(self):
        """Setup input mode (line-based, char-based) and echo-back.

        Line-based input is used if the BRZ_TEXTUI_INPUT environment
        variable is set to 'line-based', or if there is no controlling
        terminal.
        """
        is_tty = self.ui.raw_stdin.isatty()
        if (
            os.environ.get("BRZ_TEXTUI_INPUT") != "line-based"
            and self.ui.raw_stdin == _unwrap_stream(sys.stdin)
            and is_tty
        ):
            self.line_based = False
            self.echo_back = True
        else:
            self.line_based = True
            self.echo_back = not is_tty

    def _build_alternatives(self, msg, choices, default):
        """Parse choices string.

        Setup final prompt and the lists of choices and associated
        shortcuts.
        """
        index = 0
        help_list = []
        self.alternatives = {}
        choices = choices.split("\n")
        if default is not None and default not in range(0, len(choices)):
            raise ValueError("invalid default index")
        for c in choices:
            name = c.replace("&", "").lower()
            choice = (name, index)
            if name in self.alternatives:
                raise ValueError("duplicated choice: {}".format(name))
            self.alternatives[name] = choice
            shortcut = c.find("&")
            if shortcut != -1 and (shortcut + 1) < len(c):
                help = c[:shortcut]
                help += "[" + c[shortcut + 1] + "]"
                help += c[(shortcut + 2) :]
                shortcut = c[shortcut + 1]
            else:
                c = c.replace("&", "")
                shortcut = c[0]
                help = "[{}]{}".format(shortcut, c[1:])
            shortcut = shortcut.lower()
            if shortcut in self.alternatives:
                raise ValueError("duplicated shortcut: {}".format(shortcut))
            self.alternatives[shortcut] = choice
            # Add redirections for default.
            if index == default:
                self.alternatives[""] = choice
                self.alternatives["\r"] = choice
            help_list.append(help)
            index += 1

        self.prompt = "{} ({}): ".format(msg, ", ".join(help_list))

    def _getline(self):
        line = self.ui.stdin.readline()
        if line == "":
            raise EOFError
        return line.strip()

    def _getchar(self):
        char = osutils.getchar()
        if char == chr(3):  # INTR
            raise KeyboardInterrupt
        if char == chr(4):  # EOF (^d, C-d)
            raise EOFError
        if isinstance(char, bytes):
            return char.decode("ascii", "replace")
        return char

    def interact(self):
        """Keep asking the user until a valid choice is made."""
        if self.line_based:
            getchoice = self._getline
        else:
            getchoice = self._getchar
        iter = 0
        while True:
            iter += 1
            if iter == 1 or self.line_based:
                self.ui.prompt(self.prompt)
            try:
                choice = getchoice()
            except EOFError:
                self.ui.stderr.write("\n")
                return None
            except KeyboardInterrupt:
                self.ui.stderr.write("\n")
                raise
            choice = choice.lower()
            if choice not in self.alternatives:
                # Not a valid choice, keep on asking.
                continue
            name, index = self.alternatives[choice]
            if self.echo_back:
                self.ui.stderr.write(name + "\n")
            return index


opt_progress_bar = config.Option(
    "progress_bar",
    help="Progress bar type.",
    default_from_env=["BRZ_PROGRESS_BAR"],
    default=None,
    invalid="error",
)


class TextUIFactory(UIFactory):
    """A UI factory for Text user interfaces."""

    def __init__(self, stdin, stdout, stderr):
        """Create a TextUIFactory."""
        super().__init__()
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self._progress_view = NullProgressView()

    def __enter__(self):
        # Choose default encoding and handle py2/3 differences
        self._setup_streams()
        # paints progress, network activity, etc
        self._progress_view = self.make_progress_view()
        return self

    def _setup_streams(self):
        self.raw_stdin = _unwrap_stream(self.stdin)
        self.stdin = _wrap_in_stream(self.raw_stdin)
        self.raw_stdout = _unwrap_stream(self.stdout)
        self.stdout = _wrap_out_stream(self.raw_stdout)
        self.raw_stderr = _unwrap_stream(self.stderr)
        self.stderr = _wrap_out_stream(self.raw_stderr)

    def choose(self, msg, choices, default=None):
        r"""Prompt the user for a list of alternatives.

        Support both line-based and char-based editing.

        In line-based mode, both the shortcut and full choice name are valid
        answers, e.g. for choose('prompt', '&yes\n&no'): 'y', ' Y ', ' yes',
        'YES ' are all valid input lines for choosing 'yes'.

        An empty line, when in line-based mode, or pressing enter in char-based
        mode will select the default choice (if any).

        Choice is echoed back if:
        - input is char-based; which means a controlling terminal is available,
          and osutils.getchar is used
        - input is line-based, and no controlling terminal is available
        """
        choose_ui = _ChooseUI(self, msg, choices, default)
        return choose_ui.interact()

    def be_quiet(self, state):
        if state and not self._quiet:
            self.clear_term()
        UIFactory.be_quiet(self, state)
        self._progress_view = self.make_progress_view()

    def clear_term(self):
        """Prepare the terminal for output.

        This will, clear any progress bars, and leave the cursor at the
        leftmost position.
        """
        # XXX: If this is preparing to write to stdout, but that's for example
        # directed into a file rather than to the terminal, and the progress
        # bar _is_ going to the terminal, we shouldn't need
        # to clear it.  We might need to separately check for the case of
        self._progress_view.clear()

    def get_integer(self, prompt):
        while True:
            self.prompt(prompt)
            line = self.stdin.readline()
            try:
                return int(line)
            except ValueError:
                pass

    def get_non_echoed_password(self):
        isatty = getattr(self.stdin, "isatty", None)
        if isatty is not None and isatty():
            import getpass

            # getpass() ensure the password is not echoed and other
            # cross-platform niceties
            password = getpass.getpass("")
        else:
            # echo doesn't make sense without a terminal
            password = self.stdin.readline()
            if not password:
                password = None
            else:
                if password[-1] == "\n":
                    password = password[:-1]
        return password

    def get_password(self, prompt="", **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.
        :return: The password string, return None if the user
                 canceled the request.
        """
        prompt += ": "
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
        prompt += ": "
        self.prompt(prompt, **kwargs)
        username = self.stdin.readline()
        if not username:
            username = None
        else:
            if username[-1] == "\n":
                username = username[:-1]
        return username

    def make_progress_view(self):
        """Construct and return a new ProgressView subclass for this UI."""
        # with --quiet, never any progress view
        # <https://bugs.launchpad.net/bzr/+bug/320035>.  Otherwise if the
        # user specifically requests either text or no progress bars, always
        # do that.  otherwise, guess based on $TERM and tty presence.
        if self.is_quiet():
            return NullProgressView()
        pb_type = config.GlobalStack().get("progress_bar")
        if pb_type == "none":  # Explicit requirement
            return NullProgressView()
        if (
            pb_type == "text"  # Explicit requirement
            or progress._supports_progress(self.stderr)
        ):  # Guess
            return TextProgressView(self.stderr)
        # No explicit requirement and no successful guess
        return NullProgressView()

    def _make_output_stream_explicit(self, encoding, encoding_type):
        return TextUIOutputStream(self, self.stdout, encoding, encoding_type)

    def note(self, msg):
        """Write an already-formatted message, clearing the progress bar if necessary."""
        self.clear_term()
        self.stdout.write(msg + "\n")

    def prompt(self, prompt, **kwargs):
        """Emit prompt on the CLI.

        :param kwargs: Dictionary of arguments to insert into the prompt,
            to allow UIs to reformat the prompt.
        """
        if not isinstance(prompt, str):
            raise ValueError("prompt {!r} not a unicode string".format(prompt))
        if kwargs:
            # See <https://launchpad.net/bugs/365891>
            prompt = prompt % kwargs
        self.clear_term()
        self.stdout.flush()
        self.stderr.write(prompt)
        self.stderr.flush()

    def report_transport_activity(self, transport, byte_count, direction):
        """Called by transports as they do IO.

        This may update a progress bar, spinner, or similar display.
        By default it does nothing.
        """
        self._progress_view.show_transport_activity(transport, direction, byte_count)

    def log_transport_activity(self, display=False):
        """See UIFactory.log_transport_activity()."""
        log = getattr(self._progress_view, "log_transport_activity", None)
        if log is not None:
            log(display=display)

    def show_error(self, msg):
        self.clear_term()
        self.stderr.write("bzr: error: {}\n".format(msg))

    def show_message(self, msg):
        self.note(msg)

    def show_warning(self, msg):
        self.clear_term()
        self.stderr.write("bzr: warning: {}\n".format(msg))

    def _progress_updated(self, task):
        """A task has been updated and wants to be displayed."""
        if not self._task_stack:
            warnings.warn(
                "{!r} updated but no tasks are active".format(task), stacklevel=2
            )
        elif task != self._task_stack[-1]:
            # We used to check it was the top task, but it's hard to always
            # get this right and it's not necessarily useful: any actual
            # problems will be evident in use
            # warnings.warn("%r is not the top progress task %r" %
            #     (task, self._task_stack[-1]))
            pass
        self._progress_view.show_progress(task)

    def _progress_all_finished(self):
        self._progress_view.clear()

    def show_user_warning(self, warning_id, **message_args):
        """Show a text message to the user.

        Explicitly not for warnings about bzr apis, deprecations or internals.
        """
        # eventually trace.warning should migrate here, to avoid logging and
        # be easier to test; that has a lot of test fallout so for now just
        # new code can call this
        if warning_id not in self.suppressed_warnings:
            warning = self.format_user_warning(warning_id, message_args)
            self.stderr.write(warning + "\n")


def pad_to_width(line, width, encoding_hint="ascii"):
    """Truncate or pad unicode line to width.

    This is best-effort for now, and strings containing control codes or
    non-ascii text may be cut and padded incorrectly.
    """
    s = line.encode(encoding_hint, "replace")
    return (b"%-*.*s" % (width, width, s)).decode(encoding_hint)


class TextProgressView:
    """Display of progress bar and other information on a tty.

    This shows one line of text, including possibly a network indicator,
    spinner, progress bar, message, etc.

    One instance of this is created and held by the UI, and fed updates when a
    task wants to be painted.

    Transports feed data to this through the ui_factory object.

    The Progress views can comprise a tree with _parent_task pointers, but
    this only prints the stack from the nominated current task up to the root.
    """

    def __init__(self, term_file, encoding=None, errors=None):
        self._term_file = term_file
        if encoding is None:
            self._encoding = getattr(term_file, "encoding", None) or "ascii"
        else:
            self._encoding = encoding
        # true when there's output on the screen we may need to clear
        self._have_output = False
        self._last_transport_msg = ""
        self._spin_pos = 0
        # time we last repainted the screen
        self._last_repaint = 0
        # time we last got information about transport activity
        self._transport_update_time = 0
        self._last_task = None
        self._total_byte_count = 0
        self._bytes_since_update = 0
        self._bytes_by_direction = {"unknown": 0, "read": 0, "write": 0}
        self._first_byte_time = None
        self._fraction = 0
        # force the progress bar to be off, as at the moment it doesn't
        # correspond reliably to overall command progress
        self.enable_bar = False

    def _avail_width(self):
        # we need one extra space for terminals that wrap on last char
        w = osutils.terminal_width()
        if w is None:
            return None
        else:
            return w - 1

    def _show_line(self, u):
        width = self._avail_width()
        if width is not None:
            u = pad_to_width(u, width, encoding_hint=self._encoding)
        self._term_file.write("\r" + u + "\r")

    def clear(self):
        if self._have_output:
            self._show_line("")
        self._have_output = False

    def _render_bar(self):
        # return a string for the progress bar itself
        if self.enable_bar and ((self._last_task is None) or self._last_task.show_bar):
            # If there's no task object, we show space for the bar anyhow.
            # That's because most invocations of bzr will end showing progress
            # at some point, though perhaps only after doing some initial IO.
            # It looks better to draw the progress bar initially rather than
            # to have what looks like an incomplete progress bar.
            spin_str = r"/-\|"[self._spin_pos % 4]
            self._spin_pos += 1
            cols = 20
            if self._last_task is None:
                completion_fraction = 0
                self._fraction = 0
            else:
                completion_fraction = (
                    self._last_task._overall_completion_fraction() or 0
                )
            if completion_fraction < self._fraction and "progress" in debug.debug_flags:
                debug.set_trace()
            self._fraction = completion_fraction
            markers = round(float(cols) * completion_fraction) - 1
            bar_str = "[" + ("#" * markers + spin_str).ljust(cols) + "] "
            return bar_str
        elif (self._last_task is None) or self._last_task.show_spinner:
            # The last task wanted just a spinner, no bar
            spin_str = r"/-\|"[self._spin_pos % 4]
            self._spin_pos += 1
            return spin_str + " "
        else:
            return ""

    def _format_task(self, task):
        """Format task-specific parts of progress bar.

        :returns: (text_part, counter_part) both unicode strings.
        """
        if not task.show_count:
            s = ""
        elif task.current_cnt is not None and task.total_cnt is not None:
            s = " %d/%d" % (task.current_cnt, task.total_cnt)
        elif task.current_cnt is not None:
            s = " %d" % (task.current_cnt)
        else:
            s = ""
        # compose all the parent messages
        t = task
        m = task.msg
        while t._parent_task:
            t = t._parent_task
            if t.msg:
                m = t.msg + ":" + m
        return m, s

    def _render_line(self):
        bar_string = self._render_bar()
        if self._last_task:
            task_part, counter_part = self._format_task(self._last_task)
        else:
            task_part = counter_part = ""
        if self._last_task and not self._last_task.show_transport_activity:
            trans = ""
        else:
            trans = self._last_transport_msg
        # the bar separates the transport activity from the message, so even
        # if there's no bar or spinner, we must show something if both those
        # fields are present
        if (task_part or trans) and not bar_string:
            bar_string = "| "
        # preferentially truncate the task message if we don't have enough
        # space
        avail_width = self._avail_width()
        if avail_width is not None:
            # if terminal avail_width is unknown, don't truncate
            current_len = (
                len(bar_string) + len(trans) + len(task_part) + len(counter_part)
            )
            # GZ 2017-04-22: Should measure and truncate task_part properly
            gap = current_len - avail_width
            if gap > 0:
                task_part = task_part[: -gap - 2] + ".."
        s = trans + bar_string + task_part + counter_part
        if avail_width is not None:
            if len(s) < avail_width:
                s = s.ljust(avail_width)
            elif len(s) > avail_width:
                s = s[:avail_width]
        return s

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
            self._last_transport_msg = ""
        self._last_repaint = now
        self._repaint()

    def show_transport_activity(self, transport, direction, byte_count):
        """Called by transports via the ui_factory, as they do IO.

        This may update a progress bar, spinner, or similar display.
        By default it does nothing.
        """
        # XXX: there should be a transport activity model, and that too should
        #      be seen by the progress view, rather than being poked in here.
        self._total_byte_count += byte_count
        self._bytes_since_update += byte_count
        if self._first_byte_time is None:
            # Note that this isn't great, as technically it should be the time
            # when the bytes started transferring, not when they completed.
            # However, we usually start with a small request anyway.
            self._first_byte_time = time.time()
        if direction in self._bytes_by_direction:
            self._bytes_by_direction[direction] += byte_count
        else:
            self._bytes_by_direction["unknown"] += byte_count
        if "no_activity" in debug.debug_flags:
            # Can be used as a workaround if
            # <https://launchpad.net/bugs/321935> reappears and transport
            # activity is cluttering other output.  However, thanks to
            # TextUIOutputStream this shouldn't be a problem any more.
            return
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
            # using base-10 units (see HACKING.txt).
            msg = "%6dkB %5dkB/s " % (
                self._total_byte_count / 1000,
                int(rate) / 1000,
            )
            self._transport_update_time = now
            self._last_repaint = now
            self._bytes_since_update = 0
            self._last_transport_msg = msg
            self._repaint()

    def _format_bytes_by_direction(self):
        if self._first_byte_time is None:
            bps = 0.0
        else:
            transfer_time = time.time() - self._first_byte_time
            if transfer_time < 0.001:
                transfer_time = 0.001
            bps = self._total_byte_count / transfer_time

        # using base-10 units (see HACKING.txt).
        msg = "Transferred: {:.0f}kB ({:.1f}kB/s r:{:.0f}kB w:{:.0f}kB".format(
            self._total_byte_count / 1000.0,
            bps / 1000.0,
            self._bytes_by_direction["read"] / 1000.0,
            self._bytes_by_direction["write"] / 1000.0,
        )
        if self._bytes_by_direction["unknown"] > 0:
            msg += " u:%.0fkB)" % (self._bytes_by_direction["unknown"] / 1000.0)
        else:
            msg += ")"
        return msg

    def log_transport_activity(self, display=False):
        msg = self._format_bytes_by_direction()
        trace.mutter(msg)
        if display and self._total_byte_count > 0:
            self.clear()
            self._term_file.write(msg + "\n")


def _get_stream_encoding(stream):
    encoding = config.GlobalStack().get("output_encoding")
    if encoding is None:
        encoding = getattr(stream, "encoding", None)
    if encoding is None:
        encoding = osutils.get_terminal_encoding(trace=True)
    return encoding


def _unwrap_stream(stream):
    inner = getattr(stream, "buffer", None)
    if inner is None:
        inner = getattr(stream, "stream", stream)
    return inner


def _wrap_in_stream(stream, encoding=None, errors="replace"):
    if encoding is None:
        encoding = _get_stream_encoding(stream)
    # Attempt to wrap using io.open if possible, since that can do
    # line-buffering.
    try:
        fileno = stream.fileno()
    except io.UnsupportedOperation:
        encoded_stream = codecs.getreader(encoding)(stream, errors=errors)
        encoded_stream.encoding = encoding
        return encoded_stream
    else:
        return open(fileno, encoding=encoding, errors=errors, buffering=1)


def _wrap_out_stream(stream, encoding=None, errors="replace"):
    if encoding is None:
        encoding = _get_stream_encoding(stream)
    encoded_stream = codecs.getwriter(encoding)(stream, errors=errors)
    encoded_stream.encoding = encoding
    return encoded_stream


class TextUIOutputStream:
    """Decorates stream to interact better with progress and change encoding.

    Before writing to the wrapped stream, progress is cleared. Callers must
    ensure bulk output is terminated with a newline so progress won't overwrite
    partial lines.

    Additionally, the encoding and errors behaviour of the underlying stream
    can be changed at this point. If errors is set to 'exact' raw bytes may be
    written to the underlying stream.
    """

    def __init__(self, ui_factory, stream, encoding=None, errors="strict"):
        self.ui_factory = ui_factory
        # GZ 2017-05-21: Clean up semantics when callers are made saner.
        inner = _unwrap_stream(stream)
        self.raw_stream = None
        if errors == "exact":
            errors = "strict"
            self.raw_stream = inner
        if inner is None:
            self.wrapped_stream = stream
            if encoding is None:
                encoding = _get_stream_encoding(stream)
        else:
            self.wrapped_stream = _wrap_out_stream(inner, encoding, errors)
            if encoding is None:
                encoding = self.wrapped_stream.encoding
        self.encoding = encoding
        self.errors = errors

    def _write(self, to_write):
        if isinstance(to_write, bytes):
            try:
                to_write = to_write.decode(self.encoding, self.errors)
            except UnicodeDecodeError:
                self.raw_stream.write(to_write)
                return
        self.wrapped_stream.write(to_write)

    def flush(self):
        self.ui_factory.clear_term()
        self.wrapped_stream.flush()

    def write(self, to_write):
        self.ui_factory.clear_term()
        self._write(to_write)

    def writelines(self, lines):
        self.ui_factory.clear_term()
        for line in lines:
            self._write(line)
