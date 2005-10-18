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


"""Messages and logging for bazaar-ng

Messages are sent out through the Python logging library.

They can be sent to two places: to stderr, and to ~/.bzr.log.

~/.bzr.log gets all messages, and tracebacks of all uncaught
exceptions.

Normally stderr only gets messages of level INFO and higher, and gets
only a summary of exceptions, not the traceback.
"""


# TODO: in debug mode, stderr should get full tracebacks and also
# debug messages.  (Is this really needed?)

# TODO: When running the test suites, we should add an additional
# logger that sends messages into the test log file.


import sys
import os
import logging
import traceback


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
_bzr_logger.setLevel(logging.DEBUG) 

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
    """Log the last exception into the trace file.

    The exception string representation is used as the error
    summary, unless msg is given.
    """
    cmd_repr = ' '.join(repr(arg) for arg in sys.argv)
    cmd_info = '\n  command: %s\n  pwd: %s' \
        % (cmd_repr, os.getcwd())
    if msg == None:
        ei = sys.exc_info()
        msg = str(ei[1])
    if msg and (msg[-1] == '\n'):
        msg = msg[:-1]
    ## msg = "(%s) %s" % (str(type(ei[1])), msg)
    _bzr_logger.exception(msg + cmd_info)



def enable_default_logging():
    """Configure default logging to stderr and .bzr.log"""
    global _stderr_handler, _file_handler

    _stderr_handler = logging.StreamHandler()
    _stderr_handler.setFormatter(QuietFormatter())

    if not _file_handler:
        open_tracefile()

    if os.environ.get('BZR_DEBUG'):
        level = logging.DEBUG
    else:
        level = logging.INFO

    _stderr_handler.setLevel(logging.INFO)
    _file_handler.setLevel(level)

    logging.getLogger('').addHandler(_stderr_handler)


def disable_default_logging():
    """Turn off default log handlers.

    This is intended to be used by the test framework, which doesn't
    want leakage from the code-under-test into the main logs.
    """

    l = logging.getLogger('')
    l.removeHandler(_stderr_handler)
    if _file_handler:
        l.removeHandler(_file_handler)
