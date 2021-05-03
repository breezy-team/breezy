# Copyright (C) 2011 Canonical Ltd
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

"""Signal handling for the smart server code."""

import signal
import weakref

from ... import trace


# I'm pretty sure this has to be global, since signal handling is per-process.
_on_sighup = None
# TODO: Using a dict means that the order of calls is unordered. We could use a
#       list and then do something like LIFO ordering. A dict was chosen so
#       that you could have a key to easily remove your entry. However, you
#       could just use the callable itself as the indexed part, and even in
#       large cases, we shouldn't have more than 100 or so callbacks
#       registered.


def _sighup_handler(signal_number, interrupted_frame):
    """This is the actual function that is registered for handling SIGHUP.

    It will call out to all the registered functions, letting them know that a
    graceful termination has been requested.
    """
    if _on_sighup is None:
        return
    trace.mutter('Caught SIGHUP, sending graceful shutdown requests.')
    for ref in _on_sighup.valuerefs():
        try:
            cb = ref()
            if cb is not None:
                cb()
        except KeyboardInterrupt:
            raise
        except Exception:
            trace.mutter('Error occurred while running SIGHUP handlers:')
            trace.log_exception_quietly()


def install_sighup_handler():
    """Setup a handler for the SIGHUP signal."""
    if getattr(signal, "SIGHUP", None) is None:
        # If we can't install SIGHUP, there is no reason (yet) to do graceful
        # shutdown.
        old_signal = None
    else:
        old_signal = signal.signal(signal.SIGHUP, _sighup_handler)
    old_dict = _setup_on_hangup_dict()
    return old_signal, old_dict


def _setup_on_hangup_dict():
    """Create something for _on_sighup.

    This is done when we install the sighup handler, and for tests that want to
    test the functionality. If this hasn'nt been called, then
    register_on_hangup is a no-op. As is unregister_on_hangup.
    """
    global _on_sighup
    old = _on_sighup
    _on_sighup = weakref.WeakValueDictionary()
    return old


def restore_sighup_handler(orig):
    """Pass in the returned value from install_sighup_handler to reset."""
    global _on_sighup
    old_signal, old_dict = orig
    if old_signal is not None:
        signal.signal(signal.SIGHUP, old_signal)
    _on_sighup = old_dict


# TODO: Should these be single-use callables? Meaning that once we've triggered
#       SIGHUP and called them, they should auto-remove themselves? I don't
#       think so. Callers need to clean up during shutdown anyway, so that we
#       don't end up with lots of garbage in the _on_sighup dict. On the other
#       hand, we made _on_sighup a WeakValueDictionary in case cleanups didn't
#       get fired properly. Maybe we just assume we don't have to do it?
def register_on_hangup(identifier, a_callable):
    """Register for us to call a_callable as part of a graceful shutdown."""
    if _on_sighup is None:
        return
    _on_sighup[identifier] = a_callable


def unregister_on_hangup(identifier):
    """Remove a callback from being called during sighup."""
    if _on_sighup is None:
        return
    try:
        del _on_sighup[identifier]
    except KeyboardInterrupt:
        raise
    except Exception:
        # This usually runs as a tear-down step. So we don't want to propagate
        # most exceptions.
        trace.mutter('Error occurred during unregister_on_hangup:')
        trace.log_exception_quietly()
