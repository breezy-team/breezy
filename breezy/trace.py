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
from io import StringIO
import logging
import os
import sys
import time

import breezy

from .lazy_import import lazy_import
lazy_import(globals(), """
from breezy import (
    bedding,
    debug,
    osutils,
    ui,
    )
""")
from . import (
    errors,
    )


# global verbosity for breezy; controls the log level for stderr; 0=normal; <0
# is quiet; >0 is verbose.
_verbosity_level = 0

# File-like object where mutter/debug output is currently sent.  Can be
# changed by _push_log_file etc.  This is directly manipulated by some
# external code; maybe there should be functions to do that more precisely
# than push/pop_log_file.
_trace_file = None

# Absolute path for brz.log.  Not changed even if the log/trace output is
# redirected elsewhere.  Used to show the location in --version.
_brz_log_filename = None

# The time the first message was written to the trace file, so that we can
# show relative times since startup.
_brz_log_start_time = breezy._start_time


# held in a global for quick reference
_brz_logger = logging.getLogger('brz')


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


class _Bytes(str):
    """Compat class for displaying bytes on Python 2."""

    def __repr__(self):
        return 'b' + str.__repr__(self)

    def __unicode__(self):
        return self.decode('ascii', 'replace')


def mutter(fmt, *args):
    if _trace_file is None:
        return
    # XXX: Don't check this every time; instead anyone who closes the file
    # ought to deregister it.  We can tolerate None.
    if (getattr(_trace_file, 'closed', None) is not None) and _trace_file.closed:
        return

    # Let format strings be specified as ascii bytes to help Python 2
    if isinstance(fmt, bytes):
        fmt = fmt.decode('ascii', 'replace')

    if args:
        out = fmt % args
    else:
        out = fmt
    now = time.time()
    out = '%0.3f  %s\n' % (now - _brz_log_start_time, out)
    _trace_file.write(out.encode('utf-8'))
    # there's no explicit flushing; the file is typically line buffered.


def mutter_callsite(stacklevel, fmt, *args):
    """Perform a mutter of fmt and args, logging the call trace.

    :param stacklevel: The number of frames to show. None will show all
        frames.
    :param fmt: The format string to pass to mutter.
    :param args: A list of substitution variables.
    """
    import traceback
    outf = StringIO()
    if stacklevel is None:
        limit = None
    else:
        limit = stacklevel + 1
    traceback.print_stack(limit=limit, file=outf)
    formatted_lines = outf.getvalue().splitlines()
    formatted_stack = '\n'.join(formatted_lines[:-2])
    mutter(fmt + "\nCalled from:\n%s", *(args + (formatted_stack,)))


def _rollover_trace_maybe(trace_fname):
    import stat
    try:
        size = os.stat(trace_fname)[stat.ST_SIZE]
        if size <= 4 << 20:
            return
        old_fname = trace_fname + '.old'
        osutils.rename(trace_fname, old_fname)
    except OSError:
        return


def _get_brz_log_filename():
    """Return the brz log filename.

    :return: A path to the log file
    :raise EnvironmentError: If the cache directory could not be created
    """
    brz_log = os.environ.get('BRZ_LOG')
    if brz_log:
        return brz_log
    return os.path.join(bedding.cache_dir(), 'brz.log')


def _open_brz_log():
    """Open the brz.log trace file.

    If the log is more than a particular length, the old file is renamed to
    brz.log.old and a new file is started.  Otherwise, we append to the
    existing file.

    This sets the global _brz_log_filename.
    """
    global _brz_log_filename

    def _open_or_create_log_file(filename):
        """Open existing log file, or create with ownership and permissions

        It inherits the ownership and permissions (masked by umask) from
        the containing directory to cope better with being run under sudo
        with $HOME still set to the user's homedir.
        """
        flags = os.O_WRONLY | os.O_APPEND | osutils.O_TEXT
        while True:
            try:
                fd = os.open(filename, flags)
                break
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            try:
                fd = os.open(filename, flags | os.O_CREAT | os.O_EXCL, 0o666)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise
            else:
                osutils.copy_ownership_from_path(filename)
                break
        return os.fdopen(fd, 'ab', 0)  # unbuffered

    try:
        _brz_log_filename = _get_brz_log_filename()
        _rollover_trace_maybe(_brz_log_filename)

        brz_log_file = _open_or_create_log_file(_brz_log_filename)
        brz_log_file.write(b'\n')
        if brz_log_file.tell() <= 2:
            brz_log_file.write(
                b"this is a debug log for diagnosing/reporting problems in brz\n")
            brz_log_file.write(
                b"you can delete or truncate this file, or include sections in\n")
            brz_log_file.write(
                b"bug reports to https://bugs.launchpad.net/brz/+filebug\n\n")

        return brz_log_file

    except EnvironmentError as e:
        # If we are failing to open the log, then most likely logging has not
        # been set up yet. So we just write to stderr rather than using
        # 'warning()'. If we using warning(), users get the unhelpful 'no
        # handlers registered for "brz"' when something goes wrong on the
        # server. (bug #503886)
        sys.stderr.write("failed to open trace file: %s\n" % (e,))
    # TODO: What should happen if we fail to open the trace file?  Maybe the
    # objects should be pointed at /dev/null or the equivalent?  Currently
    # returns None which will cause failures later.
    return None


def enable_default_logging():
    """Configure default logging: messages to stderr and debug to brz.log

    This should only be called once per process.

    Non-command-line programs embedding breezy do not need to call this.  They
    can instead either pass a file to _push_log_file, or act directly on
    logging.getLogger("brz").

    Output can be redirected away by calling _push_log_file.

    :return: A memento from push_log_file for restoring the log state.
    """
    start_time = osutils.format_local_date(_brz_log_start_time,
                                           timezone='local')
    brz_log_file = _open_brz_log()
    if brz_log_file is not None:
        brz_log_file.write(start_time.encode('utf-8') + b'\n')
    memento = push_log_file(
        brz_log_file,
        r'[%(process)5d] %(asctime)s.%(msecs)03d %(levelname)s: %(message)s',
        r'%Y-%m-%d %H:%M:%S')
    # after hooking output into brz_log, we also need to attach a stderr
    # handler, writing only at level info and with encoding
    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    logging.getLogger('brz').addHandler(stderr_handler)
    return memento


def push_log_file(to_file, log_format=None, date_format=None):
    """Intercept log and trace messages and send them to a file.

    :param to_file: A file-like object to which messages will be sent.

    :returns: A memento that should be passed to _pop_log_file to restore the
        previously active logging.
    """
    global _trace_file
    # make a new handler
    new_handler = EncodedStreamHandler(to_file, "utf-8", level=logging.DEBUG)
    if log_format is None:
        log_format = '%(levelname)8s  %(message)s'
    new_handler.setFormatter(logging.Formatter(log_format, date_format))
    # save and remove any existing log handlers
    brz_logger = logging.getLogger('brz')
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
    #
    # save the old trace file
    old_trace_file = _trace_file
    # send traces to the new one
    _trace_file = to_file
    return ('log_memento', old_handlers, new_handler, old_trace_file, to_file)


def pop_log_file(entry):
    """Undo changes to logging/tracing done by _push_log_file.

    This flushes, but does not close the trace file (so that anything that was
    in it is output.

    Takes the memento returned from _push_log_file."""
    (magic, old_handlers, new_handler, old_trace_file, new_trace_file) = entry
    global _trace_file
    _trace_file = old_trace_file
    brz_logger = logging.getLogger('brz')
    brz_logger.removeHandler(new_handler)
    # must be closed, otherwise logging will try to close it at exit, and the
    # file will likely already be closed underneath.
    new_handler.close()
    brz_logger.handlers = old_handlers
    if new_trace_file is not None:
        new_trace_file.flush()


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


def debug_memory(message='', short=True):
    """Write out a memory dump."""
    if sys.platform == 'win32':
        from breezy import win32utils
        win32utils.debug_memory_win32api(message=message, short=short)
    else:
        _debug_memory_proc(message=message, short=short)


_short_fields = ('VmPeak', 'VmSize', 'VmRSS')


def _debug_memory_proc(message='', short=True):
    try:
        status_file = open('/proc/%s/status' % os.getpid(), 'rb')
    except IOError:
        return
    try:
        status = status_file.read()
    finally:
        status_file.close()
    if message:
        note(message)
    for line in status.splitlines():
        if not short:
            note(line)
        else:
            for field in _short_fields:
                if line.startswith(field):
                    note(line)
                    break


def _dump_memory_usage(err_file):
    import tempfile
    try:
        try:
            fd, name = tempfile.mkstemp(prefix="brz_memdump", suffix=".json")
            dump_file = os.fdopen(fd, 'w')
            from meliae import scanner
            scanner.dump_gc_objects(dump_file)
            err_file.write("Memory dumped to %s\n" % name)
        except ImportError:
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
    """Give name of error class including module for non-builtin exceptions

    If `unqualified_breezy_errors` is True, errors specific to breezy will
    also omit the module prefix.
    """
    class_name = eclass.__name__
    module_name = eclass.__module__
    if module_name in ("builtins", "exceptions", "__main__") or (
            unqualified_breezy_errors and module_name == "breezy.errors"):
        return class_name
    return "%s.%s" % (module_name, class_name)


def report_exception(exc_info, err_file):
    """Report an exception to err_file (typically stderr) and to brz.log.

    This will show either a full traceback or a short message as appropriate.

    :return: The appropriate exit code for this error.
    """
    # Log the full traceback to brz.log
    log_exception_quietly()
    if 'error' in debug.debug_flags:
        print_exception(exc_info, err_file)
        return errors.EXIT_ERROR
    exc_type, exc_object, exc_tb = exc_info
    if isinstance(exc_object, KeyboardInterrupt):
        err_file.write("brz: interrupted\n")
        return errors.EXIT_ERROR
    elif isinstance(exc_object, MemoryError):
        err_file.write("brz: out of memory\n")
        if 'mem_dump' in debug.debug_flags:
            _dump_memory_usage(err_file)
        else:
            err_file.write("Use -Dmem_dump to dump memory to a file.\n")
        return errors.EXIT_ERROR
    elif isinstance(exc_object, ImportError) \
            and str(exc_object).startswith("No module named "):
        report_user_error(
            exc_info, err_file,
            'You may need to install this Python library separately.')
        return errors.EXIT_ERROR
    elif not getattr(exc_object, 'internal_error', True):
        report_user_error(exc_info, err_file)
        return errors.EXIT_ERROR
    elif isinstance(exc_object, EnvironmentError):
        if getattr(exc_object, 'errno', None) == errno.EPIPE:
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
    err_file.write("brz: ERROR: %s: %s\n" % (
        _qualified_exception_name(exc_type), exc_object))
    err_file.write('\n')
    traceback.print_exception(exc_type, exc_object, exc_tb, file=err_file)


# TODO: Should these be specially encoding the output?
def report_user_error(exc_info, err_file, advice=None):
    """Report to err_file an error that's not an internal error.

    These don't get a traceback unless -Derror was given.

    :param exc_info: 3-tuple from sys.exc_info()
    :param advice: Extra advice to the user to be printed following the
        exception.
    """
    err_file.write(("brz: ERROR: %s\n" % (str(exc_info[1]),)))
    if advice:
        err_file.write(("%s\n" % advice))


def report_bug(exc_info, err_file):
    """Report an exception that probably indicates a bug in brz"""
    from breezy.crash import report_bug
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
    except IOError as e:
        import errno
        if e.errno in [errno.EINVAL, errno.EPIPE]:
            pass
        else:
            raise


def _flush_trace():
    # called from the breezy library finalizer returned by breezy.initialize()
    global _trace_file
    if _trace_file:
        _trace_file.flush()


class EncodedStreamHandler(logging.Handler):
    """Robustly write logging events to a stream using the specified encoding

    Messages are expected to be formatted to unicode, but UTF-8 byte strings
    are also accepted. An error during formatting or a str message in another
    encoding will be quitely noted as an error in the Bazaar log file.

    The stream is not closed so sys.stdout or sys.stderr may be passed.
    """

    def __init__(self, stream, encoding=None, errors='strict', level=0):
        logging.Handler.__init__(self, level)
        self.stream = stream
        if encoding is None:
            encoding = getattr(stream, "encoding", "ascii")
        self.encoding = encoding
        self.errors = errors

    def flush(self):
        flush = getattr(self.stream, "flush", None)
        if flush is not None:
            flush()

    def emit(self, record):
        try:
            if not isinstance(record.msg, str):
                msg = record.msg.decode("utf-8")
                record.msg = msg
            line = self.format(record)
            if not isinstance(line, str):
                line = line.decode("utf-8")
            self.stream.write(line.encode(self.encoding, self.errors) + b"\n")
        except Exception:
            log_exception_quietly()
            # Try saving the details that would have been logged in some form
            msg = args = "<Unformattable>"
            try:
                msg = repr(record.msg)
                args = repr(record.args)
            except Exception:
                pass
            # Using mutter() bypasses the logging module and writes directly
            # to the file so there's no danger of getting into a loop here.
            mutter("Logging record unformattable: %s %% %s", msg, args)


class Config(object):
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
        self._original_filename = _brz_log_filename
        self._original_state = enable_default_logging()
        return self  # This is bound to the 'as' clause in a with statement.

    def __exit__(self, exc_type, exc_val, exc_tb):
        pop_log_file(self._original_state)
        global _brz_log_filename
        _brz_log_filename = self._original_filename
        return False  # propogate exceptions.
