# Copyright (C) 2009 Canonical Ltd
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

"""Helpers for managing cleanup functions and the errors they might raise.

Generally, code that wants to perform some cleanup at the end of an action will
look like this::

    from bzrlib.cleanups import run_cleanup
    try:
        do_something()
    finally:
        run_cleanup(cleanup_something)

Any errors from `cleanup_something` will be logged, but not raised.
Importantly, any errors from do_something will be propagated.

If a failure in a cleanup function should be reported to a user, then use::

    run_cleanup_reporting_errors(cleanup_something)

This will emit a trace.warning with the error in addition to logging it.

There is also convenience function for running multiple, independent cleanups
in sequence: run_cleanups.  e.g.::

    try:
        do_something()
    finally:
        run_cleanups([cleanup_func_a, cleanup_func_b], ...)

Developers can use the `-Dcleanup` debug flag to cause cleanup errors to be
reported in the UI as well as logged.

XXX: what about the case where do_something succeeds, but cleanup fails, and
that matters?

XXX: perhaps this:

    do_with_cleanups(do_something, cleanups)

    this can be pedantically correct, at the cost of inconveniencing the
    callsite.
"""


import sys
from bzrlib import (
    debug,
    trace,
    )

def _log_cleanup_error(exc):
    trace.mutter('Cleanup failed:')
    trace.log_exception_quietly()
    if 'cleanup' in debug.debug_flags:
        trace.warning('bzr: warning: Cleanup failed: %s', exc)


def run_cleanup(func, *args, **kwargs):
    """Run func(*args, **kwargs), logging but not propagating any error it
    raises.

    :returns: True if func raised no errors, else False.
    """
    try:
        func(*args, **kwargs)
    except KeyboardInterrupt:
        raise
    except Exception, exc:
        _log_cleanup_error(exc)
        return False
    return True


#def run_cleanup_reporting_errors(func, *args, **kwargs):
#    try:
#        func(*args, **kwargs)
#    except KeyboardInterrupt:
#        raise
#    except Exception, exc:
#        trace.mutter('Cleanup failed:')
#        trace.log_exception_quietly()
#        trace.warning('Cleanup failed: %s', exc)
#        return False
#    return True


def run_cleanups(funcs, on_error='log'):
    """

    :param errors: One of 'log', 'warn first', 'warn all'
    """
    seen_error = False
    for func in funcs:
        if on_error == 'log' or (on_error == 'warn first' and seen_error):
            seen_error |= run_cleanup(func)
        else:
            seen_error |= run_cleanup_reporting_errors(func)


#  - ? what about -Dcleanup, should it influnce do_with_cleanups' behaviour?

def do_with_cleanups(func, cleanup_funcs):
    # As correct as Python 2.4 allows.
    try:
        result = func()
    except:
        # We have an exception from func already, so suppress cleanup errors.
        run_cleanups(cleanup_funcs)
        raise
    else:
        # No exception from func, so allow the first exception from
        # cleanup_funcs to propagate if one occurs (but only after running all
        # of them).
        exc_info = None
        for cleanup in cleanup_funcs:
            # XXX: Hmm, if KeyboardInterrupt arrives at exactly this line, we
            # won't run all cleanups...
            if exc_info is None:
                try:
                    cleanup()
                except:
                    # XXX: should this never swallow KeyboardInterrupt, etc?
                    # This is the first cleanup to fail, so remember its
                    # details.
                    exc_info = sys.exc_info()
            else:
                # We already have an exception to propagate, so log any errors
                # but don't propagate them.
                run_cleanup(cleanup)
        if exc_info is not None:
            raise exc_info[0], exc_info[1], exc_info[2]
        # No error, so we can return the result
        return result


