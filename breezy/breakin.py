# Copyright (C) 2007, 2009, 2010 Canonical Ltd
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

r"""Signal handling for debugging support.

This module provides functionality to hook a debugger into signal handlers,
allowing developers to drop into a debugger when specific signals are received.
On Unix systems, this uses SIGQUIT (Ctrl-\), and on Windows, it uses SIGBREAK
(Ctrl-Pause).
"""

import os
import signal

_breakin_signal_number: int | None = None
_breakin_signal_name: str | None = None


def _debug(signal_number, interrupted_frame):
    import pdb
    import sys

    sys.stderr.write(
        f"** {_breakin_signal_name} received, entering debugger\n"
        "** Type 'c' to continue or 'q' to stop the process\n"
        f"** Or {_breakin_signal_name} again to quit (and possibly dump core)\n"
    )
    # It seems that on Windows, when sys.stderr is to a PIPE, then we need to
    # flush. Not sure why it is buffered, but that seems to be the case.
    sys.stderr.flush()
    # restore default meaning so that you can kill the process by hitting it
    # twice
    if _breakin_signal_number is None:
        raise AssertionError
    signal.signal(_breakin_signal_number, signal.SIG_DFL)
    try:
        pdb.set_trace()
    finally:
        signal.signal(_breakin_signal_number, _debug)


def determine_signal():
    """Determine the appropriate signal to use for debugging breakin.

    Checks for platform-specific signals and sets the global signal number
    and name variables. On Unix-like systems, SIGQUIT is used, while on
    Windows, SIGBREAK is used.

    Returns:
        Optional[int]: The signal number to use for debugging breakin,
            or None if no appropriate signal is available.
    """
    global _breakin_signal_number
    global _breakin_signal_name
    if _breakin_signal_number is not None:
        return _breakin_signal_number
    # Note: As near as I can tell, Windows is the only one to define SIGBREAK,
    #       and other platforms defined SIGQUIT. There doesn't seem to be a
    #       platform that defines both.
    #       -- jam 2009-07-30
    sigquit = getattr(signal, "SIGQUIT", None)
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigquit is not None:
        _breakin_signal_number = sigquit
        _breakin_signal_name = "SIGQUIT"
    elif sigbreak is not None:
        _breakin_signal_number = sigbreak
        _breakin_signal_name = "SIGBREAK"

    return _breakin_signal_number


def hook_debugger_to_signal():
    r"""Add a signal handler so we drop into the debugger.

    On Unix, this is hooked into SIGQUIT (C-\), and on Windows, this is
    hooked into SIGBREAK (C-Pause).
    """
    # when sigquit (C-\) or sigbreak (C-Pause) is received go into pdb
    if os.environ.get("BRZ_SIGQUIT_PDB", "1") == "0":
        # User explicitly requested we don't support this
        return
    sig = determine_signal()
    if sig is None:
        return
    # print 'hooking into %s' % (_breakin_signal_name,)
    signal.signal(sig, _debug)
