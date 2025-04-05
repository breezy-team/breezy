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

"""Messages and logging.

Messages are supplied by callers as a string-formatting template, plus values
to be inserted into it.  The actual %-formatting is deferred to the log
library so that it doesn't need to be done for messages that won't be emitted.

Messages are classified by severity levels: critical, error, warning, info,
and debug.

They can be sent to two places: stderr, and `$XDG_CACHE_HOME/breezy/brz.log`.
For purposes such as running the test suite, they can also be redirected away
from both of those two places to another location.

`brz.log` gets all messages, and full tracebacks for uncaught exceptions.
This trace file is always in UTF-8, regardless of the user's default encoding,
so that we can always rely on writing any message.

Output to stderr depends on the mode chosen by the user.  By default, messages
of info and above are sent out, which results in progress messages such as the
list of files processed by add and commit.  In debug mode, stderr gets debug messages too.

Errors that terminate an operation are generally passed back as exceptions;
others may be just emitted as messages.

Exceptions are reported in a brief form to stderr so as not to look scary.
BzrErrors are required to be able to format themselves into a properly
explanatory message.  This is not true for builtin exceptions such as
KeyError, which typically just str to "0".  They're printed in a different
form.
"""

# FIXME: Unfortunately it turns out that python's logging module
# is quite expensive, even when the message is not printed by any handlers.
# We should perhaps change back to just simply doing it here.
#
# On the other hand, as of 1.2 we generally only call the mutter() statement
# if (according to debug_flags) we actually intend to write it.  So the
# increased cost of logging.py is not so bad, and we could standardize on
# that.

import errno
import logging
import os
import sys
from io import StringIO

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy import (
    ui,
    )
""",
)
from . import _cmd_rs, debug, errors

# global verbosity for breezy; controls the log level for stderr; 0=normal; <0
# is quiet; >0 is verbose.
_verbosity_level = 0

# held in a global for quick reference
_brz_logger = logging.getLogger("brz")

_trace_handler = None


def note(*args, **kwargs):
    """Output a note to the user.

    Takes the same parameters as logging.info.

    :return: None
    """
    # FIXME: clearing the ui and then going through the abstract logging
    # framework is whack; we should probably have a logging Handler that
    # deals with terminal output if needed.
    ui.ui_factory.clear_term()
    _brz_logger.info(*args, **kwargs)


def warning(*args, **kwargs):
    ui.ui_factory.clear_term()
    _brz_logger.warning(*args, **kwargs)


def show_error(*args, **kwargs):
    """Show an error message to the user.

    Don't use this for exceptions, use report_exception instead.
    """
    _brz_logger.error(*args, **kwargs)


def mutter(fmt, *args):
    global _trace_handler
    if _trace_handler is None:
        return

    # Let format strings be specified as ascii bytes to help Python 2
    if isinstance(fmt, bytes):
        fmt = fmt.decode("ascii", "replace")

    out = fmt % args if args else fmt

    _trace_handler.mutter(out)


def mutter_callsite(stacklevel, fmt, *args):
    """Perform a mutter of fmt and args, logging the call trace.

    :param stacklevel: The number of frames to show. None will show all
        frames.
    :param fmt: The format string to pass to mutter.
    :param args: A list of substitution variables.
    """
    import traceback

    outf = StringIO()
    limit = None if stacklevel is None else stacklevel + 1
    traceback.print_stack(limit=limit, file=outf)
    formatted_lines = outf.getvalue().splitlines()
    formatted_stack = "\n".join(formatted_lines[:-2])
    mutter(fmt + "\nCalled from:\n%s", *(args + (formatted_stack,)))


_rollover_trace_maybe = _cmd_rs.rollover_trace_maybe
_initialize_brz_log_filename = _cmd_rs.initialize_brz_log_filename
_open_brz_log = _cmd_rs.open_brz_log
get_brz_log_filename = _cmd_rs.get_brz_log_filename
set_brz_log_filename = _cmd_rs.set_brz_log_filename


def enable_default_logging():
    """Configure default logging: messages to stderr and debug to brz.log.

    This should only be called once per process.

    Non-command-line programs embedding breezy do not need to call this.  They
    can instead either pass a file to _push_log_file, or act directly on
    logging.getLogger("brz").

    Output can be redirected away by calling _push_log_file.

    :return: A memento from push_log_file for restoring the log state.
    """
    brz_log_file = _open_brz_log()
    # TODO: What should happen if we fail to open the trace file?  Maybe the
    # objects should be pointed at /dev/null or the equivalent?  Currently
    # returns None which will cause failures later.
    if brz_log_file is None:
        return None
    memento = push_log_file(brz_log_file, short=False)
    # after hooking output into brz_log, we also need to attach a stderr
    # handler, writing only at level info and with encoding
    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    logging.getLogger("brz").addHandler(stderr_handler)
    return memento


def push_log_file(to_file, short=True):
    """Intercept log and trace messages and send them to a file.

    :param to_file: A file-like object to which messages will be sent.

    :returns: A memento that should be passed to _pop_log_file to restore the
        previously active logging.
    """
    global _trace_handler
    # make a new handler
    old_trace_handler = _trace_handler
    _trace_handler = new_handler = _cmd_rs.BreezyTraceHandler(to_file, short=short)
    # save and remove any existing log handlers
    brz_logger = logging.getLogger("brz")
    old_handlers = brz_logger.handlers[:]
    del brz_logger.handlers[:]
    # set that as the default logger
    brz_logger.addHandler(new_handler)
    brz_logger.setLevel(logging.DEBUG)
    # TODO: check if any changes are needed to the root logger
    #
    # TODO: also probably need to save and restore the level on brz_logger.
    # but maybe we can avoid setting the logger level altogether, and just set
    # the level on the handler?
    return ("log_memento", old_handlers, new_handler, old_trace_handler)


def pop_log_file(entry):
    """Undo changes to logging/tracing done by _push_log_file.

    This flushes, but does not close the trace file (so that anything that was
    in it is output.

    Takes the memento returned from _push_log_file.
    """
    (magic, old_handlers, new_handler, old_trace_handler) = entry
    global _trace_handler
    _trace_handler = old_trace_handler
    brz_logger = logging.getLogger("brz")
    brz_logger.removeHandler(new_handler)
    # must be closed, otherwise logging will try to close it at exit, and the
    # file will likely already be closed underneath.
    new_handler.close()
    brz_logger.handlers = old_handlers


def log_exception_quietly():
    """Log the last exception to the trace file only.

    Used for exceptions that occur internally and that may be
    interesting to developers but not to users.  For example,
    errors loading plugins.
    """
    import traceback

    mutter(traceback.format_exc())


def set_verbosity_level(level):
    """Set the verbosity level.

    :param level: -ve for quiet, 0 for normal, +ve for verbose
    """
    global _verbosity_level
    _verbosity_level = level
    _update_logging_level(level < 0)
    ui.ui_factory.be_quiet(level < 0)


def get_verbosity_level():
    """Get the verbosity level.

    See set_verbosity_level() for values.
    """
    return _verbosity_level


def be_quiet(quiet=True):
    if quiet:
        set_verbosity_level(-1)
    else:
        set_verbosity_level(0)


def _update_logging_level(quiet=True):
    """Hide INFO messages if quiet."""
    if quiet:
        _brz_logger.setLevel(logging.WARNING)
    else:
        _brz_logger.setLevel(logging.INFO)


def is_quiet():
    """Is the verbosity level negative?"""
    return _verbosity_level < 0


def is_verbose():
    """Is the verbosity level positive?"""
    return _verbosity_level > 0


def debug_memory(message="", short=True):
    """Write out a memory dump."""
    if sys.platform == "win32":
        from breezy import win32utils

        win32utils.debug_memory_win32api(message=message, short=short)
    else:
        _debug_memory_proc(message=message, short=short)


_debug_memory_proc = _cmd_rs.debug_memory_proc


def _dump_memory_usage(err_file):
    import tempfile

    try:
        try:
            fd, name = tempfile.mkstemp(prefix="brz_memdump", suffix=".json")
            dump_file = os.fdopen(fd, "w")
            from meliae import scanner

            scanner.dump_gc_objects(dump_file)
            err_file.write(f"Memory dumped to {name}\n")
        except ModuleNotFoundError:
            err_file.write("Dumping memory requires meliae module.\n")
            log_exception_quietly()
        except BaseException:
            err_file.write("Exception while dumping memory.\n")
            log_exception_quietly()
    finally:
        if dump_file is not None:
            dump_file.close()
        elif fd is not None:
            os.close(fd)


def _qualified_exception_name(eclass, unqualified_breezy_errors=False):
    """Give name of error class including module for non-builtin exceptions.

    If `unqualified_breezy_errors` is True, errors specific to breezy will
    also omit the module prefix.
    """
    class_name = eclass.__name__
    module_name = eclass.__module__
    if module_name in ("builtins", "exceptions", "__main__") or (
        unqualified_breezy_errors and module_name == "breezy.errors"
    ):
        return class_name
    return f"{module_name}.{class_name}"


def report_exception(exc_info, err_file):
    """Report an exception to err_file (typically stderr) and to brz.log.

    This will show either a full traceback or a short message as appropriate.

    :return: The appropriate exit code for this error.
    """
    # Log the full traceback to brz.log
    log_exception_quietly()
    if debug.debug_flag_enabled("error"):
        print_exception(exc_info, err_file)
        return errors.EXIT_ERROR
    exc_type, exc_object, exc_tb = exc_info
    if isinstance(exc_object, KeyboardInterrupt):
        err_file.write("brz: interrupted\n")
        return errors.EXIT_ERROR
    elif isinstance(exc_object, MemoryError):
        err_file.write("brz: out of memory\n")
        if debug.debug_flag_enabled("mem_dump"):
            _dump_memory_usage(err_file)
        else:
            err_file.write("Use -Dmem_dump to dump memory to a file.\n")
        return errors.EXIT_ERROR
    elif isinstance(exc_object, ModuleNotFoundError):
        report_user_error(
            exc_info,
            err_file,
            "You may need to install this Python library separately.",
        )
        return errors.EXIT_ERROR
    elif not getattr(exc_object, "internal_error", True):
        report_user_error(exc_info, err_file)
        return errors.EXIT_ERROR
    elif isinstance(exc_object, EnvironmentError):
        if getattr(exc_object, "errno", None) == errno.EPIPE:
            err_file.write("brz: broken pipe\n")
            return errors.EXIT_ERROR
        # Might be nice to catch all of these and show them as something more
        # specific, but there are too many cases at the moment.
        report_user_error(exc_info, err_file)
        return errors.EXIT_ERROR
    else:
        report_bug(exc_info, err_file)
        return errors.EXIT_INTERNAL_ERROR


def print_exception(exc_info, err_file):
    import traceback

    exc_type, exc_object, exc_tb = exc_info
    err_file.write(f"brz: ERROR: {_qualified_exception_name(exc_type)}: {exc_object}\n")
    err_file.write("\n")
    traceback.print_exception(exc_type, exc_object, exc_tb, file=err_file)


# TODO: Should these be specially encoding the output?
def report_user_error(exc_info, err_file, advice=None):
    """Report to err_file an error that's not an internal error.

    These don't get a traceback unless -Derror was given.

    :param exc_info: 3-tuple from sys.exc_info()
    :param advice: Extra advice to the user to be printed following the
        exception.
    """
    err_file.write(f"brz: ERROR: {exc_info[1]!s}\n")
    if advice:
        err_file.write(f"{advice}\n")


def report_bug(exc_info, err_file):
    """Report an exception that probably indicates a bug in brz."""
    from .crash import report_bug

    report_bug(exc_info, err_file)


def _flush_stdout_stderr():
    # called from the breezy library finalizer returned by breezy.initialize()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except ValueError:
        # On Windows, I get ValueError calling stdout.flush() on a closed
        # handle
        pass
    except OSError as e:
        import errno

        if e.errno in [errno.EINVAL, errno.EPIPE]:
            pass
        else:
            raise


def _flush_trace():
    # called from the breezy library finalizer returned by breezy.initialize()
    global _trace_handler
    if _trace_handler:
        _trace_handler.flush()


class Config:
    """Configuration of message tracing in breezy.

    This implements the context manager protocol and should manage any global
    variables still used. The default config used is DefaultConfig, but
    embedded uses of breezy may wish to use a custom manager.
    """

    def __enter__(self):
        return self  # This is bound to the 'as' clause in a with statement.

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False  # propogate exceptions.


class DefaultConfig(Config):
    """A default configuration for tracing of messages in breezy.

    This implements the context manager protocol.
    """

    def __enter__(self):
        self._original_filename = get_brz_log_filename()
        self._original_state = enable_default_logging()
        return self  # This is bound to the 'as' clause in a with statement.

    def __exit__(self, exc_type, exc_val, exc_tb):
        pop_log_file(self._original_state)
        _cmd_rs.set_brz_log_filename(self._original_filename)
        return False  # propogate exceptions.
