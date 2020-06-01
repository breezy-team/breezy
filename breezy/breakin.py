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

import os
import signal


_breakin_signal_number = None
_breakin_signal_name = None


def _debug(signal_number, interrupted_frame):
    import pdb
    import sys
    sys.stderr.write("** %s received, entering debugger\n"
                     "** Type 'c' to continue or 'q' to stop the process\n"
                     "** Or %s again to quit (and possibly dump core)\n"
                     % (_breakin_signal_name, _breakin_signal_name))
    # It seems that on Windows, when sys.stderr is to a PIPE, then we need to
    # flush. Not sure why it is buffered, but that seems to be the case.
    sys.stderr.flush()
    # restore default meaning so that you can kill the process by hitting it
    # twice
    signal.signal(_breakin_signal_number, signal.SIG_DFL)
    try:
        pdb.set_trace()
    finally:
        signal.signal(_breakin_signal_number, _debug)


def determine_signal():
    global _breakin_signal_number
    global _breakin_signal_name
    if _breakin_signal_number is not None:
        return _breakin_signal_number
    # Note: As near as I can tell, Windows is the only one to define SIGBREAK,
    #       and other platforms defined SIGQUIT. There doesn't seem to be a
    #       platform that defines both.
    #       -- jam 2009-07-30
    sigquit = getattr(signal, 'SIGQUIT', None)
    sigbreak = getattr(signal, 'SIGBREAK', None)
    if sigquit is not None:
        _breakin_signal_number = sigquit
        _breakin_signal_name = 'SIGQUIT'
    elif sigbreak is not None:
        _breakin_signal_number = sigbreak
        _breakin_signal_name = 'SIGBREAK'

    return _breakin_signal_number


def hook_debugger_to_signal():
    """Add a signal handler so we drop into the debugger.

    On Unix, this is hooked into SIGQUIT (C-\\), and on Windows, this is
    hooked into SIGBREAK (C-Pause).
    """

    # when sigquit (C-\) or sigbreak (C-Pause) is received go into pdb
    if os.environ.get('BRZ_SIGQUIT_PDB', '1') == '0':
        # User explicitly requested we don't support this
        return
    sig = determine_signal()
    if sig is None:
        return
    # print 'hooking into %s' % (_breakin_signal_name,)
    signal.signal(sig, _debug)
