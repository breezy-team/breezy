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

def _debug(signal_number, interrupted_frame):
    import pdb
    import sys
    sys.stderr.write("** SIGQUIT received, entering debugger\n"
            "** Type 'c' to continue or 'q' to stop the process\n")
    pdb.set_trace()

def hook_sigquit():
    # when sigquit (C-\) is received go into pdb
    # XXX: is this meaningful on Windows?
    import signal
    signal.signal(signal.SIGQUIT, _debug)
