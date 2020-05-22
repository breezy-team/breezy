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

This currently just contains a copy of contextlib.ExitStack, available
even on older versions of Python.
"""

from __future__ import absolute_import

from collections import deque
import sys


try:
    from contextlib import ExitStack
except ImportError:
    # Copied from the Python standard library on Python 3.4.
    # Copyright: Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008,
    #   2009, 2010, 2011 Python Software Foundation
    #
    # PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2
    # --------------------------------------------
    # .
    # 1. This LICENSE AGREEMENT is between the Python Software Foundation
    # ("PSF"), and the Individual or Organization ("Licensee") accessing and
    # otherwise using this software ("Python") in source or binary form and
    # its associated documentation.
    # .
    # 2. Subject to the terms and conditions of this License Agreement, PSF hereby
    # grants Licensee a nonexclusive, royalty-free, world-wide license to reproduce,
    # analyze, test, perform and/or display publicly, prepare derivative works,
    # distribute, and otherwise use Python alone or in any derivative version,
    # provided, however, that PSF's License Agreement and PSF's notice of copyright,
    # i.e., "Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010,
    # 2011 Python Software Foundation; All Rights Reserved" are retained in Python
    # alone or in any derivative version prepared by Licensee.
    # .
    # 3. In the event Licensee prepares a derivative work that is based on
    # or incorporates Python or any part thereof, and wants to make
    # the derivative work available to others as provided herein, then
    # Licensee hereby agrees to include in any such work a brief summary of
    # the changes made to Python.
    # .
    # 4. PSF is making Python available to Licensee on an "AS IS"
    # basis.  PSF MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
    # IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, PSF MAKES NO AND
    # DISCLAIMS ANY REPRESENTATION OR WARRANTY OF MERCHANTABILITY OR FITNESS
    # FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF PYTHON WILL NOT
    # INFRINGE ANY THIRD PARTY RIGHTS.
    # .
    # 5. PSF SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF PYTHON
    # FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS AS
    # A RESULT OF MODIFYING, DISTRIBUTING, OR OTHERWISE USING PYTHON,
    # OR ANY DERIVATIVE THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.
    # .
    # 6. This License Agreement will automatically terminate upon a material
    # breach of its terms and conditions.
    # .
    # 7. Nothing in this License Agreement shall be deemed to create any
    # relationship of agency, partnership, or joint venture between PSF and
    # Licensee.  This License Agreement does not grant permission to use PSF
    # trademarks or trade name in a trademark sense to endorse or promote
    # products or services of Licensee, or any third party.
    # .
    # 8. By copying, installing or otherwise using Python, Licensee
    # agrees to be bound by the terms and conditions of this License
    # Agreement.

    def _reraise_with_existing_context(exc_details):
        # Use 3 argument raise in Python 2,
        # but use exec to avoid SyntaxError in Python 3
        exc_type, exc_value, exc_tb = exc_details
        exec("raise exc_type, exc_value, exc_tb")


    # Inspired by discussions on http://bugs.python.org/issue13585
    class ExitStack(object):
        """Context manager for dynamic management of a stack of exit callbacks

        For example:

            with ExitStack() as stack:
                files = [stack.enter_context(open(fname)) for fname in filenames]
                # All opened files will automatically be closed at the end of
                # the with statement, even if attempts to open files later
                # in the list raise an exception

        """
        def __init__(self):
            self._exit_callbacks = deque()

        def pop_all(self):
            """Preserve the context stack by transferring it to a new instance"""
            new_stack = type(self)()
            new_stack._exit_callbacks = self._exit_callbacks
            self._exit_callbacks = deque()
            return new_stack

        def _push_cm_exit(self, cm, cm_exit):
            """Helper to correctly register callbacks to __exit__ methods"""
            def _exit_wrapper(*exc_details):
                return cm_exit(cm, *exc_details)
            _exit_wrapper.__self__ = cm
            self.push(_exit_wrapper)

        def push(self, exit):
            """Registers a callback with the standard __exit__ method signature

            Can suppress exceptions the same way __exit__ methods can.

            Also accepts any object with an __exit__ method (registering a call
            to the method instead of the object itself)
            """
            # We use an unbound method rather than a bound method to follow
            # the standard lookup behaviour for special methods
            _cb_type = type(exit)
            try:
                exit_method = _cb_type.__exit__
            except AttributeError:
                # Not a context manager, so assume its a callable
                self._exit_callbacks.append(exit)
            else:
                self._push_cm_exit(exit, exit_method)
            return exit # Allow use as a decorator

        def callback(self, callback, *args, **kwds):
            """Registers an arbitrary callback and arguments.

            Cannot suppress exceptions.
            """
            def _exit_wrapper(exc_type, exc, tb):
                callback(*args, **kwds)
            # We changed the signature, so using @wraps is not appropriate, but
            # setting __wrapped__ may still help with introspection
            _exit_wrapper.__wrapped__ = callback
            self.push(_exit_wrapper)
            return callback # Allow use as a decorator

        def enter_context(self, cm):
            """Enters the supplied context manager

            If successful, also pushes its __exit__ method as a callback and
            returns the result of the __enter__ method.
            """
            # We look up the special methods on the type to match the with statement
            _cm_type = type(cm)
            _exit = _cm_type.__exit__
            result = _cm_type.__enter__(cm)
            self._push_cm_exit(cm, _exit)
            return result

        def close(self):
            """Immediately unwind the context stack"""
            self.__exit__(None, None, None)

        def __enter__(self):
            return self

        def __exit__(self, *exc_details):
            received_exc = exc_details[0] is not None

            # We manipulate the exception state so it behaves as though
            # we were actually nesting multiple with statements
            frame_exc = sys.exc_info()[1]
            def _make_context_fixer(frame_exc):
                return lambda new_exc, old_exc: None
            _fix_exception_context = _make_context_fixer(frame_exc)

            # Callbacks are invoked in LIFO order to match the behaviour of
            # nested context managers
            suppressed_exc = False
            pending_raise = False
            while self._exit_callbacks:
                cb = self._exit_callbacks.pop()
                try:
                    if cb(*exc_details):
                        suppressed_exc = True
                        pending_raise = False
                        exc_details = (None, None, None)
                except:
                    new_exc_details = sys.exc_info()
                    # simulate the stack of exceptions by setting the context
                    _fix_exception_context(new_exc_details[1], exc_details[1])
                    pending_raise = True
                    exc_details = new_exc_details
            if pending_raise:
                _reraise_with_existing_context(exc_details)
            return received_exc and suppressed_exc
