# Copyright (C) 2009, 2010 Canonical Ltd
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

The usual way to run cleanup code in Python is::

    try:
        do_something()
    finally:
        cleanup_something()

However if both `do_something` and `cleanup_something` raise an exception
Python will forget the original exception and propagate the one from
cleanup_something.  Unfortunately, this is almost always much less useful than
the original exception.

If you want to be certain that the first, and only the first, error is raised,
then use::

    operation = OperationWithCleanups(do_something)
    operation.add_cleanup(cleanup_something)
    operation.run_simple()

This is more inconvenient (because you need to make every try block a
function), but will ensure that the first error encountered is the one raised,
while also ensuring all cleanups are run.  See OperationWithCleanups for more
details.
"""

from __future__ import absolute_import

from collections import deque
from . import (
    debug,
    trace,
    )


def _log_cleanup_error(exc):
    trace.mutter('Cleanup failed:')
    trace.log_exception_quietly()
    if 'cleanup' in debug.debug_flags:
        trace.warning('brz: warning: Cleanup failed: %s', exc)


def _run_cleanup(func, *args, **kwargs):
    """Run func(*args, **kwargs), logging but not propagating any error it
    raises.

    :returns: True if func raised no errors, else False.
    """
    try:
        func(*args, **kwargs)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        _log_cleanup_error(exc)
        return False
    return True


def _run_cleanups(funcs):
    """Run a series of cleanup functions."""
    for func, args, kwargs in funcs:
        _run_cleanup(func, *args, **kwargs)


class ObjectWithCleanups(object):
    """A mixin for objects that hold a cleanup list.

    Subclass or client code can call add_cleanup and then later `cleanup_now`.
    """

    def __init__(self):
        self.cleanups = deque()

    def add_cleanup(self, cleanup_func, *args, **kwargs):
        """Add a cleanup to run.

        Cleanups may be added at any time.
        Cleanups will be executed in LIFO order.
        """
        self.cleanups.appendleft((cleanup_func, args, kwargs))

    def cleanup_now(self):
        _run_cleanups(self.cleanups)
        self.cleanups.clear()


class OperationWithCleanups(ObjectWithCleanups):
    """A way to run some code with a dynamic cleanup list.

    This provides a way to add cleanups while the function-with-cleanups is
    running.

    Typical use::

        operation = OperationWithCleanups(some_func)
        operation.run(args...)

    where `some_func` is::

        def some_func(operation, args, ...):
            do_something()
            operation.add_cleanup(something)
            # etc

    Note that the first argument passed to `some_func` will be the
    OperationWithCleanups object.  To invoke `some_func` without that, use
    `run_simple` instead of `run`.
    """

    def __init__(self, func):
        super(OperationWithCleanups, self).__init__()
        self.func = func

    def run(self, *args, **kwargs):
        return _do_with_cleanups(
            self.cleanups, self.func, self, *args, **kwargs)

    def run_simple(self, *args, **kwargs):
        return _do_with_cleanups(
            self.cleanups, self.func, *args, **kwargs)


def _do_with_cleanups(cleanup_funcs, func, *args, **kwargs):
    """Run `func`, then call all the cleanup_funcs.

    All the cleanup_funcs are guaranteed to be run.  The first exception raised
    by func or any of the cleanup_funcs is the one that will be propagted by
    this function (subsequent errors are caught and logged).

    Conceptually similar to::

        try:
            return func(*args, **kwargs)
        finally:
            for cleanup, cargs, ckwargs in cleanup_funcs:
                cleanup(*cargs, **ckwargs)

    It avoids several problems with using try/finally directly:
     * an exception from func will not be obscured by a subsequent exception
       from a cleanup.
     * an exception from a cleanup will not prevent other cleanups from
       running (but the first exception encountered is still the one
       propagated).

    Unike `_run_cleanup`, `_do_with_cleanups` can propagate an exception from a
    cleanup, but only if there is no exception from func.
    """
    try:
        result = func(*args, **kwargs)
    except BaseException:
        # We have an exception from func already, so suppress cleanup errors.
        _run_cleanups(cleanup_funcs)
        raise
    # No exception from func, so allow first cleanup error to propgate.
    pending_cleanups = iter(cleanup_funcs)
    try:
        for cleanup, c_args, c_kwargs in pending_cleanups:
            cleanup(*c_args, **c_kwargs)
    except BaseException:
        # Still run the remaining cleanups but suppress any further errors.
        _run_cleanups(pending_cleanups)
        raise
    # No error, so we can return the result
    return result
