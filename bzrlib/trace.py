# Copyright (C) 2005, Canonical Ltd

"""Messages and logging for bazaar-ng.

Messages are supplied by callers as a string-formatting template, plus values
to be inserted into it.  The actual %-formatting is deferred to the log
library so that it doesn't need to be done for messages that won't be emitted.

Messages are classified by severity levels: critical, error, warning, info,
and debug.

They can be sent to two places: to stderr, and to ~/.bzr.log.  For purposes
such as running the test suite, they can also be redirected away from both of
those two places to another location.

~/.bzr.log gets all messages, and full tracebacks for uncaught exceptions.
This trace file is always in UTF-8, regardless of the user's default encoding,
so that we can always rely on writing any message.

Output to stderr depends on the mode chosen by the user.  By default, messages
of info and above are sent out, which results in progress messages such as the
list of files processed by add and commit.  In quiet mode, only warnings and
above are shown.  In debug mode, stderr gets debug messages too.

Errors that terminate an operation are generally passed back as exceptions;
others may be just emitted as messages.

Exceptions are reported in a brief form to stderr so as not to look scary.
BzrErrors are required to be able to format themselves into a properly
explanatory message.  This is not true for builtin excexceptions such as
KeyError, which typically just str to "0".  They're printed in a different
form.
"""

# TODO: in debug mode, stderr should get full tracebacks and also
# debug messages.  (Is this really needed?)

# FIXME: Unfortunately it turns out that python's logging module
# is quite expensive, even when the message is not printed by any handlers.
# We should perhaps change back to just simply doing it here.


import sys
import os
import logging

import bzrlib
from bzrlib.errors import BzrNewError


_file_handler = None
_stderr_handler = None
_stderr_quiet = False
_trace_file = None
_bzr_log_file = None

class QuietFormatter(logging.Formatter):
    """Formatter that supresses the details of errors.

    This is used by default on stderr so as not to scare the user.
    """
    # At first I tried overriding formatException to suppress the
    # exception details, but that has global effect: no loggers
    # can get the exception details is we suppress them here.

    def format(self, record):
        if record.levelno >= logging.WARNING:
            s = 'bzr: ' + record.levelname + ': '
        else:
            s = ''
        s += record.getMessage()
        if record.exc_info:
            s += '\n' + format_exception_short(record.exc_info)
        return s
        
# configure convenient aliases for output routines

_bzr_logger = logging.getLogger('bzr')

info = note = _bzr_logger.info
warning =   _bzr_logger.warning
log_error = _bzr_logger.error
error =     _bzr_logger.error


def mutter(fmt, *args):
    if _trace_file is None:
        return
    if hasattr(_trace_file, 'closed') and _trace_file.closed:
        return
    if len(args) > 0:
        out = fmt % args
    else:
        out = fmt
    out += '\n'
    if isinstance(out, unicode):
        out = out.encode('utf-8')
    _trace_file.write(out)
debug = mutter


def _rollover_trace_maybe(trace_fname):
    import stat
    try:
        size = os.stat(trace_fname)[stat.ST_SIZE]
        if size <= 4 << 20:
            return
        old_fname = trace_fname + '.old'
        from osutils import rename
        rename(trace_fname, old_fname)
    except OSError:
        return


def open_tracefile(tracefilename='~/.bzr.log'):
    # Messages are always written to here, so that we have some
    # information if something goes wrong.  In a future version this
    # file will be removed on successful completion.
    global _file_handler, _bzr_log_file
    import stat, codecs

    trace_fname = os.path.join(os.path.expanduser(tracefilename))
    _rollover_trace_maybe(trace_fname)
    try:
        LINE_BUFFERED = 1
        tf = codecs.open(trace_fname, 'at', 'utf8', buffering=LINE_BUFFERED)
        _bzr_log_file = tf
        if tf.tell() == 0:
            tf.write("\nthis is a debug log for diagnosing/reporting problems in bzr\n")
            tf.write("you can delete or truncate this file, or include sections in\n")
            tf.write("bug reports to bazaar-ng@lists.canonical.com\n\n")
        _file_handler = logging.StreamHandler(tf)
        fmt = r'[%(process)5d] %(asctime)s.%(msecs)03d %(levelname)s: %(message)s'
        datefmt = r'%a %H:%M:%S'
        _file_handler.setFormatter(logging.Formatter(fmt, datefmt))
        _file_handler.setLevel(logging.DEBUG)
        logging.getLogger('').addHandler(_file_handler)
    except IOError, e:
        warning("failed to open trace file: %s" % (e))


def log_startup(argv):
    debug('\n\nbzr %s invoked on python %s (%s)',
          bzrlib.__version__,
          '.'.join(map(str, sys.version_info)),
          sys.platform)
    debug('  arguments: %r', argv)
    debug('  working dir: %r', os.getcwdu())


def log_exception(msg=None):
    """Log the last exception to stderr and the trace file.

    The exception string representation is used as the error
    summary, unless msg is given.
    """
    if msg:
        error(msg)
    else:
        exc_str = format_exception_short(sys.exc_info())
        error(exc_str)
    log_exception_quietly()


def log_exception_quietly():
    """Log the last exception to the trace file only.

    Used for exceptions that occur internally and that may be 
    interesting to developers but not to users.  For example, 
    errors loading plugins.
    """
    import traceback
    debug(traceback.format_exc())


def enable_default_logging():
    """Configure default logging to stderr and .bzr.log"""
    # FIXME: if this is run twice, things get confused
    global _stderr_handler, _file_handler, _trace_file, _bzr_log_file
    _stderr_handler = logging.StreamHandler()
    _stderr_handler.setFormatter(QuietFormatter())
    logging.getLogger('').addHandler(_stderr_handler)
    _stderr_handler.setLevel(logging.INFO)
    if not _file_handler:
        open_tracefile()
    _trace_file = _bzr_log_file
    if _file_handler:
        _file_handler.setLevel(logging.DEBUG)
    _bzr_logger.setLevel(logging.DEBUG) 



def be_quiet(quiet=True):
    global _stderr_handler, _stderr_quiet
    
    _stderr_quiet = quiet
    if quiet:
        _stderr_handler.setLevel(logging.WARNING)
    else:
        _stderr_handler.setLevel(logging.INFO)


def is_quiet():
    global _stderr_quiet
    return _stderr_quiet


def disable_default_logging():
    """Turn off default log handlers.

    This is intended to be used by the test framework, which doesn't
    want leakage from the code-under-test into the main logs.
    """

    l = logging.getLogger('')
    l.removeHandler(_stderr_handler)
    if _file_handler:
        l.removeHandler(_file_handler)
    _trace_file = None


def enable_test_log(to_file):
    """Redirect logging to a temporary file for a test"""
    disable_default_logging()
    global _test_log_hdlr, _trace_file
    hdlr = logging.StreamHandler(to_file)
    hdlr.setLevel(logging.DEBUG)
    hdlr.setFormatter(logging.Formatter('%(levelname)8s  %(message)s'))
    _bzr_logger.addHandler(hdlr)
    _bzr_logger.setLevel(logging.DEBUG)
    _test_log_hdlr = hdlr
    _trace_file = to_file


def disable_test_log():
    _bzr_logger.removeHandler(_test_log_hdlr)
    _trace_file = None
    enable_default_logging()


def format_exception_short(exc_info):
    """Make a short string form of an exception.

    This is used for display to stderr.  It specially handles exception
    classes without useful string methods.

    The result has no trailing newline.

    exc_info - typically an exception from sys.exc_info()
    """
    exc_type, exc_object, exc_tb = exc_info
    try:
        if exc_type is None:
            return '(no exception)'
        if isinstance(exc_object, BzrNewError):
            return str(exc_object)
        else:
            import traceback
            tb = traceback.extract_tb(exc_tb)
            msg = '%s: %s' % (exc_type, exc_object)
            if msg[-1] == '\n':
                msg = msg[:-1]
            if tb:
                msg += '\n  at %s line %d\n  in %s' % (tb[-1][:3])
            return msg
    except:
        return '(error formatting exception of type %s)' % exc_type
