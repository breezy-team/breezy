# Copyright (C) 2006 Canonical Ltd

import pdb
import signal
import sys

def _debug(signal_number, interrupted_frame):
    sys.stderr.write("** SIGQUIT received, entering debugger\n"
            "** Type 'c' to continue or 'q' to stop the process\n")
    pdb.set_trace()

def hook_sigquit():
    # when sigquit (C-\) is received go into pdb
    # XXX: is this meaningful on Windows?
    signal.signal(signal.SIGQUIT, _debug)


