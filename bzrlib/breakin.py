# Copyright (C) 2006, 2007 Canonical Ltd
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

import os
import signal

def _debug(signal_number, interrupted_frame):
    import pdb
    import sys
    sys.stderr.write("** SIGQUIT received, entering debugger\n"
            "** Type 'c' to continue or 'q' to stop the process\n"
            "** Or SIGQUIT again to quit (and possibly dump core)\n"
            )
    # restore default meaning so that you can kill the process by hitting it
    # twice
    signal.signal(signal.SIGQUIT, signal.SIG_DFL)
    try:
        pdb.set_trace()
    finally:
        signal.signal(signal.SIGQUIT, _debug)


def hook_sigquit():
    # when sigquit (C-\) is received go into pdb
    # XXX: is this meaningful on Windows?
    if os.environ.get('BZR_SIGQUIT_PDB', '1') == '0':
        return
    signal.signal(signal.SIGQUIT, _debug)
