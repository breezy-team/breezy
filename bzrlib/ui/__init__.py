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

"""Abstraction for interacting with the user.

Applications can choose different types of UI, and they deal with displaying
messages or progress to the user, and with gathering different types of input.

Several levels are supported, and you can also register new factories such as
for a GUI.

bzrlib.ui.UIFactory
    Semi-abstract base class

bzrlib.ui.SilentUIFactory
    Produces no output and cannot take any input; useful for programs using
    bzrlib in batch mode or for programs such as loggerhead.

bzrlib.ui.CannedInputUIFactory
    For use in testing; the input values to be returned are provided 
    at construction.

bzrlib.ui.text.TextUIFactory
    Standard text command-line interface, with stdin, stdout, stderr.
    May make more or less advanced use of them, eg in drawing progress bars,
    depending on the detected capabilities of the terminal.
    GUIs may choose to subclass this so that unimplemented methods fall
    back to working through the terminal.
"""


import warnings

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    osutils,
    progress,
    trace,
    )
""")


_valid_boolean_strings = dict(yes=True, no=False,
                              y=True, n=False,
                              on=True, off=False,
                              true=True, false=False)
_valid_boolean_strings['1'] = True
_valid_boolean_strings['0'] = False


def bool_from_string(s, accepted_values=None):
    """Returns a boolean if the string can be interpreted as such.

    Interpret case insensitive strings as booleans. The default values
    includes: 'yes', 'no, 'y', 'n', 'true', 'false', '0', '1', 'on',
    'off'. Alternative values can be provided with the 'accepted_values'
    parameter.

    :param s: A string that should be interpreted as a boolean. It should be of
        type string or unicode.

    :param accepted_values: An optional dict with accepted strings as keys and
        True/False as values. The strings will be tested against a lowered
        version of 's'.

    :return: True or False for accepted strings, None otherwise.
    """
    if accepted_values is None:
        accepted_values = _valid_boolean_strings
    val = None
    if type(s) in (str, unicode):
        try:
            val = accepted_values[s.lower()]
        except KeyError:
            pass
    return val


class ConfirmationUserInterfacePolicy(object):
    """Wrapper for a UIFactory that allows or denies all confirmed actions."""

    def __init__(self, wrapped_ui, default_answer, specific_answers):
        """Generate a proxy UI that does no confirmations.

        :param wrapped_ui: Underlying UIFactory.
        :param default_answer: Bool for whether requests for
            confirmation from the user should be noninteractively accepted or
            denied.
        :param specific_answers: Map from confirmation_id to bool answer.
        """
        self.wrapped_ui = wrapped_ui
        self.default_answer = default_answer
        self.specific_answers = specific_answers

    def __getattr__(self, name):
        return getattr(self.wrapped_ui, name)

    def __repr__(self):
        return '%s(%r, %r, %r)' % (
            self.__class__.__name__,
            self.wrapped_ui,
            self.default_answer, 
            self.specific_answers)

    def confirm_action(self, prompt, confirmation_id, prompt_kwargs):
        if confirmation_id in self.specific_answers:
            return self.specific_answers[confirmation_id]
        elif self.default_answer is not None:
            return self.default_answer
        else:
            return self.wrapped_ui.confirm_action(
                prompt, confirmation_id, prompt_kwargs)


class UIFactory(object):
    """UI abstraction.

    This tells the library how to display things to the user.  Through this
    layer different applications can choose the style of UI.

    UI Factories are also context managers, for some syntactic sugar some users
    need.

    :ivar suppressed_warnings: Identifiers for user warnings that should 
        no be emitted.
    """

    _user_warning_templates = dict(
        cross_format_fetch=("Doing on-the-fly conversion from "
            "%(from_format)s to %(to_format)s.\n"
            "This may take some time. Upgrade the repositories to the "
            "same format for better performance."
            ),
        deprecated_command=(
            "The command 'bzr %(deprecated_name)s' "
            "has been deprecated in bzr %(deprecated_in_version)s. "
            "Please use 'bzr %(recommended_name)s' instead."),
        recommend_upgrade=("%(current_format_name)s is deprecated "
            "and a better format is available.\n"
            "It is recommended that you upgrade by "
            "running the command\n"
            "  bzr upgrade %(basedir)s"),
        )

    def __init__(self):
        self._task_stack = []
        self.suppressed_warnings = set()
        self._quiet = False

    def __enter__(self):
        """Context manager entry support.

        Override in a concrete factory class if initialisation before use is
        needed.
        """
        return self # This is bound to the 'as' clause in a with statement.

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit support.

        Override in a concrete factory class if more cleanup than a simple
        self.clear_term() is needed when the UIFactory is finished with.
        """
        self.clear_term()
        return False # propogate exceptions.

    def be_quiet(self, state):
        """Tell the UI to be more quiet, or not.

        Typically this suppresses progress bars; the application may also look
        at ui_factory.is_quiet().
        """
        self._quiet = state

    def confirm_action(self, prompt, confirmation_id, prompt_kwargs):
        """Seek user confirmation for an action.

        If the UI is noninteractive, or the user does not want to be asked
        about this action, True is returned, indicating bzr should just
        proceed.

        The confirmation id allows the user to configure certain actions to
        always be confirmed or always denied, and for UIs to specialize the
        display of particular confirmations.

        :param prompt: Suggested text to display to the user.
        :param prompt_kwargs: A dictionary of arguments that can be
            string-interpolated into the prompt.
        :param confirmation_id: Unique string identifier for the confirmation.
        """
        return self.get_boolean(prompt % prompt_kwargs)

    def get_password(self, prompt=u'', **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user (must be unicode)
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.

        :return: The password string, return None if the user canceled the
                 request. Note that we do not touch the encoding, users may
                 have whatever they see fit and the password should be
                 transported as is.
        """
        raise NotImplementedError(self.get_password)

    def is_quiet(self):
        return self._quiet

    def make_output_stream(self, encoding=None, encoding_type=None):
        """Get a stream for sending out bulk text data.

        This is used for commands that produce bulk text, such as log or diff
        output, as opposed to user interaction.  This should work even for
        non-interactive user interfaces.  Typically this goes to a decorated
        version of stdout, but in a GUI it might be appropriate to send it to a 
        window displaying the text.
     
        :param encoding: Unicode encoding for output; if not specified 
            uses the configured 'output_encoding' if any; otherwise the 
            terminal encoding. 
            (See get_terminal_encoding.)

        :param encoding_type: How to handle encoding errors:
            replace/strict/escape/exact.  Default is replace.
        """
        # XXX: is the caller supposed to close the resulting object?
        if encoding is None:
            from bzrlib import config
            encoding = config.GlobalConfig().get_user_option(
                'output_encoding')
        if encoding is None:
            encoding = osutils.get_terminal_encoding(trace=True)
        if encoding_type is None:
            encoding_type = 'replace'
        out_stream = self._make_output_stream_explicit(encoding, encoding_type)
        return out_stream

    def _make_output_stream_explicit(self, encoding, encoding_type):
        raise NotImplementedError("%s doesn't support make_output_stream"
            % (self.__class__.__name__))

    def nested_progress_bar(self):
        """Return a nested progress bar.

        When the bar has been finished with, it should be released by calling
        bar.finished().
        """
        if self._task_stack:
            t = progress.ProgressTask(self._task_stack[-1], self)
        else:
            t = progress.ProgressTask(None, self)
        self._task_stack.append(t)
        return t

    def _progress_finished(self, task):
        """Called by the ProgressTask when it finishes"""
        if not self._task_stack:
            warnings.warn("%r finished but nothing is active"
                % (task,))
        if task in self._task_stack:
            self._task_stack.remove(task)
        else:
            warnings.warn("%r is not in active stack %r"
                % (task, self._task_stack))
        if not self._task_stack:
            self._progress_all_finished()

    def _progress_all_finished(self):
        """Called when the top-level progress task finished"""
        pass

    def _progress_updated(self, task):
        """Called by the ProgressTask when it changes.

        Should be specialized to draw the progress.
        """
        pass

    def clear_term(self):
        """Prepare the terminal for output.

        This will, for example, clear text progress bars, and leave the
        cursor at the leftmost position.
        """
        pass

    def format_user_warning(self, warning_id, message_args):
        try:
            template = self._user_warning_templates[warning_id]
        except KeyError:
            fail = "failed to format warning %r, %r" % (warning_id, message_args)
            warnings.warn(fail)   # so tests will fail etc
            return fail
        try:
            return template % message_args
        except ValueError, e:
            fail = "failed to format warning %r, %r: %s" % (
                warning_id, message_args, e)
            warnings.warn(fail)   # so tests will fail etc
            return fail

    def get_boolean(self, prompt):
        """Get a boolean question answered from the user.

        :param prompt: a message to prompt the user with. Should be a single
            line without terminating \\n.
        :return: True or False for y/yes or n/no.
        """
        raise NotImplementedError(self.get_boolean)

    def get_integer(self, prompt):
        """Get an integer from the user.

        :param prompt: a message to prompt the user with. Could be a multi-line
            prompt but without a terminating \\n.

        :return: A signed integer.
        """
        raise NotImplementedError(self.get_integer)

    def make_progress_view(self):
        """Construct a new ProgressView object for this UI.

        Application code should normally not call this but instead
        nested_progress_bar().
        """
        return NullProgressView()

    def recommend_upgrade(self, current_format_name, basedir):
        """Recommend the user upgrade a control directory.

        :param current_format_name: Description of the current format
        :param basedir: Location of the control dir
        """
        self.show_user_warning('recommend_upgrade',
            current_format_name=current_format_name, basedir=basedir)

    def report_transport_activity(self, transport, byte_count, direction):
        """Called by transports as they do IO.

        This may update a progress bar, spinner, or similar display.
        By default it does nothing.
        """
        pass

    def log_transport_activity(self, display=False):
        """Write out whatever transport activity has been measured.

        Implementations are allowed to do nothing, but it is useful if they can
        write a line to the log file.

        :param display: If False, only log to disk, if True also try to display
            a message to the user.
        :return: None
        """
        # Default implementation just does nothing
        pass

    def show_user_warning(self, warning_id, **message_args):
        """Show a warning to the user.

        This is specifically for things that are under the user's control (eg
        outdated formats), not for internal program warnings like deprecated
        APIs.

        This can be overridden by UIFactory subclasses to show it in some 
        appropriate way; the default UIFactory is noninteractive and does
        nothing.  format_user_warning maps it to a string, though other
        presentations can be used for particular UIs.

        :param warning_id: An identifier like 'cross_format_fetch' used to 
            check if the message is suppressed and to look up the string.
        :param message_args: Arguments to be interpolated into the message.
        """
        pass

    def show_error(self, msg):
        """Show an error message (not an exception) to the user.
        
        The message should not have an error prefix or trailing newline.  That
        will be added by the factory if appropriate.
        """
        raise NotImplementedError(self.show_error)

    def show_message(self, msg):
        """Show a message to the user."""
        raise NotImplementedError(self.show_message)

    def show_warning(self, msg):
        """Show a warning to the user."""
        raise NotImplementedError(self.show_warning)

    def warn_cross_format_fetch(self, from_format, to_format):
        """Warn about a potentially slow cross-format transfer.
        
        This is deprecated in favor of show_user_warning, but retained for api
        compatibility in 2.0 and 2.1.
        """
        self.show_user_warning('cross_format_fetch', from_format=from_format,
            to_format=to_format)

    def warn_experimental_format_fetch(self, inter):
        """Warn about fetching into experimental repository formats."""
        if inter.target._format.experimental:
            trace.warning("Fetching into experimental format %s.\n"
                "This format may be unreliable or change in the future "
                "without an upgrade path.\n" % (inter.target._format,))


class NoninteractiveUIFactory(UIFactory):
    """Base class for UIs with no user."""

    def confirm_action(self, prompt, confirmation_id, prompt_kwargs):
        return True

    def __repr__(self):
        return '%s()' % (self.__class__.__name__, )


class SilentUIFactory(NoninteractiveUIFactory):
    """A UI Factory which never prints anything.

    This is the default UI, if another one is never registered by a program
    using bzrlib, and it's also active for example inside 'bzr serve'.

    Methods that try to read from the user raise an error; methods that do
    output do nothing.
    """

    def __init__(self):
        UIFactory.__init__(self)

    def note(self, msg):
        pass

    def get_username(self, prompt, **kwargs):
        return None

    def _make_output_stream_explicit(self, encoding, encoding_type):
        return NullOutputStream(encoding)

    def show_error(self, msg):
        pass

    def show_message(self, msg):
        pass

    def show_warning(self, msg):
        pass


class CannedInputUIFactory(SilentUIFactory):
    """A silent UI that return canned input."""

    def __init__(self, responses):
        self.responses = responses

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.responses)

    def confirm_action(self, prompt, confirmation_id, args):
        return self.get_boolean(prompt % args)

    def get_boolean(self, prompt):
        return self.responses.pop(0)

    def get_integer(self, prompt):
        return self.responses.pop(0)

    def get_password(self, prompt=u'', **kwargs):
        return self.responses.pop(0)

    def get_username(self, prompt, **kwargs):
        return self.responses.pop(0)

    def assert_all_input_consumed(self):
        if self.responses:
            raise AssertionError("expected all input in %r to be consumed"
                % (self,))


ui_factory = SilentUIFactory()
# IMPORTANT: never import this symbol directly. ONLY ever access it as
# ui.ui_factory, so that you refer to the current value.


def make_ui_for_terminal(stdin, stdout, stderr):
    """Construct and return a suitable UIFactory for a text mode program.
    """
    # this is now always TextUIFactory, which in turn decides whether it
    # should display progress bars etc
    from bzrlib.ui.text import TextUIFactory
    return TextUIFactory(stdin, stdout, stderr)


class NullProgressView(object):
    """Soak up and ignore progress information."""

    def clear(self):
        pass

    def show_progress(self, task):
        pass

    def show_transport_activity(self, transport, direction, byte_count):
        pass

    def log_transport_activity(self, display=False):
        pass


class NullOutputStream(object):
    """Acts like a file, but discard all output."""

    def __init__(self, encoding):
        self.encoding = encoding

    def write(self, data):
        pass

    def writelines(self, data):
        pass

    def close(self):
        pass
