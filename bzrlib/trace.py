# Copyright (C) 2005, 2006 by Canonical Ltd
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
explanatory message.  This is not true for builtin exceptions such as
KeyError, which typically just str to "0".  They're printed in a different
form.
"""

# FIXME: Unfortunately it turns out that python's logging module
# is quite expensive, even when the message is not printed by any handlers.
# We should perhaps change back to just simply doing it here.


import errno
import os
import sys
import logging

import bzrlib
from bzrlib.errors import BzrError, BzrNewError
from bzrlib.symbol_versioning import (deprecated_function,
        zero_nine,
        )

_file_handler = None
_stderr_handler = None
_stderr_quiet = False
_trace_file = None
_trace_depth = 0
_bzr_log_file = None


# configure convenient aliases for output routines

_bzr_logger = logging.getLogger('bzr')

def note(*args, **kwargs):
    # FIXME note always emits utf-8, regardless of the terminal encoding
    import bzrlib.ui
    bzrlib.ui.ui_factory.clear_term()
    _bzr_logger.info(*args, **kwargs)

def warning(*args, **kwargs):
    import bzrlib.ui
    bzrlib.ui.ui_factory.clear_term()
    _bzr_logger.warning(*args, **kwargs)

info = note
log_error = _bzr_logger.error
error =     _bzr_logger.error


def mutter(fmt, *args):
    if _trace_file is None:
        return
    if (getattr(_trace_file, 'closed', None) is not None) and _trace_file.closed:
        return

    if isinstance(fmt, unicode):
        fmt = fmt.encode('utf8')

    if len(args) > 0:
        # It seems that if we do ascii % (unicode, ascii) we can
        # get a unicode cannot encode ascii error, so make sure that "fmt"
        # is a unicode string
        real_args = []
        for arg in args:
            if isinstance(arg, unicode):
                arg = arg.encode('utf8')
            real_args.append(arg)
        out = fmt % tuple(real_args)
    else:
        out = fmt
    out += '\n'
    _trace_file.write(out)
    # TODO: jam 20051227 Consider flushing the trace file to help debugging
    #_trace_file.flush()
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
    import codecs

    trace_fname = os.path.join(os.path.expanduser(tracefilename))
    _rollover_trace_maybe(trace_fname)
    try:
        LINE_BUFFERED = 1
        #tf = codecs.open(trace_fname, 'at', 'utf8', buffering=LINE_BUFFERED)
        tf = open(trace_fname, 'at', LINE_BUFFERED)
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


@deprecated_function(zero_nine)
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
    """Redirect logging to a temporary file for a test
    
    returns an opaque reference that should be passed to disable_test_log
    after the test completes.
    """
    disable_default_logging()
    global _trace_file
    global _trace_depth
    hdlr = logging.StreamHandler(to_file)
    hdlr.setLevel(logging.DEBUG)
    hdlr.setFormatter(logging.Formatter('%(levelname)8s  %(message)s'))
    _bzr_logger.addHandler(hdlr)
    _bzr_logger.setLevel(logging.DEBUG)
    result = hdlr, _trace_file, _trace_depth
    _trace_file = to_file
    _trace_depth += 1
    return result


def disable_test_log((test_log_hdlr, old_trace_file, old_trace_depth)):
    _bzr_logger.removeHandler(test_log_hdlr)
    test_log_hdlr.close()
    global _trace_file
    global _trace_depth
    _trace_file = old_trace_file
    _trace_depth = old_trace_depth
    if not _trace_depth:
        enable_default_logging()


def report_exception(exc_info, err_file):
    exc_type, exc_object, exc_tb = exc_info
    # Log the full traceback to ~/.bzr.log
    log_exception_quietly()
    if (isinstance(exc_object, IOError)
        and getattr(exc_object, 'errno', None) == errno.EPIPE):
        print >>err_file, "bzr: broken pipe"
    elif isinstance(exc_object, KeyboardInterrupt):
        print >>err_file, "bzr: interrupted"
    elif getattr(exc_object, 'is_user_error', False):
        report_user_error(exc_info, err_file)
    elif isinstance(exc_object, (OSError, IOError)):
        # Might be nice to catch all of these and show them as something more
        # specific, but there are too many cases at the moment.
        report_user_error(exc_info, err_file)
    else:
        report_bug(exc_info, err_file)


# TODO: Should these be specially encoding the output?
def report_user_error(exc_info, err_file):
    print >>err_file, "bzr: ERROR:", str(exc_info[1])


def report_bug(exc_info, err_file):
    """Report an exception that probably indicates a bug in bzr"""
    import traceback
    exc_type, exc_object, exc_tb = exc_info
    print >>err_file, "bzr: ERROR: %s: %s" % (exc_type, exc_object)
    print >>err_file
    traceback.print_exception(exc_type, exc_object, exc_tb, file=err_file)
    print >>err_file
    print >>err_file, 'bzr %s on python %s (%s)' % \
                       (bzrlib.__version__,
                        '.'.join(map(str, sys.version_info)),
                        sys.platform)
    print >>err_file, 'arguments: %r' % sys.argv
    print >>err_file
    print >>err_file, "** please send this report to bazaar-ng@lists.ubuntu.com"
