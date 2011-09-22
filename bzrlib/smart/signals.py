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

from bzrlib import trace


# I'm pretty sure this has to be global, since signal handling is per-process.
_on_sighup = weakref.WeakValueDictionary()
# TODO: Using a dict means that the order of calls is unordered. We could use a
#       list and then do something like LIFO ordering. A dict was chosen so
#       that you could have a key to easily remove your entry. However, you
#       could just use the callable itself as the indexed part, and even in
#       large cases, we shouldn't have more than 100 or so callbacks
#       registered.
def _sighup_handler(signal_number, interrupted_frame):
    for ref in _on_sighup.valuerefs():
        # TODO: ignore errors here
        try:
            cb = ref()
            if cb is not None:
                cb()
        except KeyboardInterrupt:
            raise
        except Exception:
            trace.mutter('Error occurred while running SIGHUP handlers:')
            trace.log_exception_quietly()


# TODO: One option, we could require install_sighup_handler to be called,
#       before we allocate _on_sighup. And then register_on_hangup would become
#       a no-op if install_sighup_handler was never installed. This would help
#       us avoid creating garbage if the test suite isn't going to handle it.
def install_sighup_handler():
    """Setup a handler for the SIGHUP signal."""
    signal.signal(signal.SIGHUP, _sighup_handler)


# TODO: Should these be single-use callables? Meaning that once we've triggered
#       SIGHUP and called them, they should auto-remove themselves? I don't
#       think so. Callers need to clean up during shutdown anyway, so that we
#       don't end up with lots of garbage in the _on_sighup dict. On the other
#       hand, we made _on_sighup a WeakValueDictionary in case cleanups didn't
#       get fired properly. Maybe we just assume we don't have to do it?
def register_on_hangup(identifier, a_callable):
    """Register for us to call a_callable as part of a graceful shutdown."""
    _on_sighup[identifier] = a_callable


def unregister_on_hangup(identifier):
    """Remove a callback from being called during sighup."""
    try:
        del _on_sighup[identifier]
    except KeyboardInterrupt:
        raise
    except Exception:
        # This usually runs as a tear-down step. So we don't want to propagate
        # most exceptions.
        trace.mutter('Error occurred during unregister_on_hangup:')
        trace.log_exception_quietly()

