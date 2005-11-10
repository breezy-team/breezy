# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

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

# TODO: When running the test suites, we should add an additional
# logger that sends messages into the test log file.

# FIXME: Unfortunately it turns out that python's logging module
# is quite expensive, even when the message is not printed by any handlers.
# We should perhaps change back to just simply doing it here.


import sys
import os
import logging
import traceback

from bzrlib.errors import BzrNewError


_file_handler = None
_stderr_handler = None


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

        ##import textwrap
        ##s = textwrap.fill(s)
            
        if record.exc_info:
            # give just a summary of the exception, not the whole thing
            exinfo = traceback.extract_tb(record.exc_info[2])
            # the format of this string matches one of the REs
            s += '\n'
            s += ('  at %s line %d, in %s()\n' % exinfo[-1][:3])
            s += '  see ~/.bzr.log for debug information'

        return s
        



################
# configure convenient aliases for output routines

_bzr_logger = logging.getLogger('bzr')

info = note = _bzr_logger.info
warning =   _bzr_logger.warning
log_error = _bzr_logger.error
error =     _bzr_logger.error
mutter =    _bzr_logger.debug
debug =     _bzr_logger.debug




# we do the rollover using this code, rather than the default from python
# logging, because we only want to rollover at program startup, not on each
# message.  maybe that's not a good enough reason.

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
    global _file_handler
    import stat, codecs

    trace_fname = os.path.join(os.path.expanduser(tracefilename))
    _rollover_trace_maybe(trace_fname)

    # buffering=1 means line buffered
    try:
        tf = codecs.open(trace_fname, 'at', 'utf8', buffering=1)

        if os.fstat(tf.fileno())[stat.ST_SIZE] == 0:
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
    import bzrlib

    debug('bzr %s invoked on python %s (%s)',
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
    ei = sys.exc_info()
    if msg == None:
        msg = str(ei[1])
    if msg and (msg[-1] == '\n'):
        msg = msg[:-1]
    msg += '\n  command: %s' % ' '.join(repr(arg) for arg in sys.argv)
    msg += '\n      pwd: %r' % os.getcwdu()
    msg += '\n    error: %s' % ei[0]        # exception type
    _bzr_logger.exception(msg)


def log_exception_quietly():
    """Log the last exception to the trace file only.

    Used for exceptions that occur internally and that may be 
    interesting to developers but not to users.  For example, 
    errors loading plugins.
    """
    debug(traceback.format_exc())


def enable_default_logging():
    """Configure default logging to stderr and .bzr.log"""
    global _stderr_handler, _file_handler

    _stderr_handler = logging.StreamHandler()
    _stderr_handler.setFormatter(QuietFormatter())
    logging.getLogger('').addHandler(_stderr_handler)

    if os.environ.get('BZR_DEBUG'):
        level = logging.DEBUG
    else:
        level = logging.INFO

    _stderr_handler.setLevel(logging.INFO)

    if not _file_handler:
        open_tracefile()

    if _file_handler:
        _file_handler.setLevel(level)

    _bzr_logger.setLevel(level) 

def disable_default_logging():
    """Turn off default log handlers.

    This is intended to be used by the test framework, which doesn't
    want leakage from the code-under-test into the main logs.
    """

    l = logging.getLogger('')
    l.removeHandler(_stderr_handler)
    if _file_handler:
        l.removeHandler(_file_handler)


def format_exception_short():
    """Make a short string form of an exception.

    This is used for display to stderr.  It specially handles exception
    classes without useful string methods.

    The result has no trailing newline.
    """
    exc_type, exc_info, exc_tb = sys.exc_info()
    if exc_type is None:
        return '(no exception)'
    if isinstance(exc_info, BzrNewError):
        return str(exc_info)
    else:
        import traceback
        tb = traceback.extract_tb(exc_tb)
        msg = '%s: %s' % (exc_type, exc_info)
        if msg[-1] == '\n':
            msg = msg[:-1]
        if tb:
            msg += '\n  at %s line %d\n  in %s' % (tb[-1][:3])
        return msg
