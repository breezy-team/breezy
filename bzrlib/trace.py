#! /usr/bin/env python
# -*- coding: UTF-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


__copyright__ = "Copyright (C) 2005 Canonical Ltd."
__author__ = "Martin Pool <mbp@canonical.com>"


import sys, os, time, socket, stat, codecs
import bzrlib

######################################################################
# messages and logging

## TODO: If --verbose is given then write to both stderr and
## _tracefile; perhaps replace _tracefile with a tee thing.

global _tracefile, _starttime
_tracefile = None

# used to have % (os.environ['USER'], time.time(), os.getpid()), 'w')
_starttime = None

# If false, notes also go to stdout; should replace this with --silent
# at some point.
silent = False


# TODO: Somehow tie this to the --verbose option?
verbose = False


def warning(msg):
    b = 'bzr: warning: ' + msg + '\n'
    sys.stderr.write(b)
    _tracefile.write(b)
    #_tracefile.flush()

def mutter(msg):
    _tracefile.write(msg)
    _tracefile.write('\n')
    # _tracefile.flush()
    if verbose:
        sys.stderr.write('- ' + msg + '\n')


def note(msg):
    b = '* ' + str(msg) + '\n'
    if not silent:
        sys.stderr.write(b)
    _tracefile.write(b)
    # _tracefile.flush()


def log_error(msg):
    sys.stderr.write(msg)
    _tracefile.write(msg)
    # _tracefile.flush()



def create_tracefile(argv):
    # TODO: Also show contents of /etc/lsb-release, if it can be parsed.
    #       Perhaps that should eventually go into the platform library?
    # TODO: If the file doesn't exist, add a note describing it.

    # Messages are always written to here, so that we have some
    # information if something goes wrong.  In a future version this
    # file will be removed on successful completion.
    global _starttime, _tracefile

    _starttime = os.times()[4]

    # XXX:  Does this always work on Windows?
    trace_fname = os.path.join(os.path.expanduser('~/.bzr.log'))
    _tracefile = codecs.open(trace_fname, 'at', 'utf8')
    t = _tracefile

    if os.fstat(t.fileno())[stat.ST_SIZE] == 0:
        t.write("\nthis is a debug log for diagnosing/reporting problems in bzr\n")
        t.write("you can delete or truncate this file, or include sections in\n")
        t.write("bug reports to bazaar-ng@lists.canonical.com\n\n")

    # TODO: If we failed to create the file, perhaps give a warning
    # but don't abort; send things to /dev/null instead?

    
    t.write('-' * 60 + '\n')
    t.write('bzr invoked at %s\n' % bzrlib.osutils.format_date(time.time()))
    t.write('  version: %s\n' % bzrlib.__version__)
    t.write('  by %s on %s\n' % (bzrlib.osutils.username(), socket.getfqdn()))
    t.write('  arguments: %r\n' % argv)
    t.write('  working dir: %s\n' % os.getcwdu())

    t.write('  platform: %s\n' % sys.platform)
    t.write('  python: %s\n' % (sys.version_info,))

    import atexit
    atexit.register(_close_trace)


def _close_trace():
    times = os.times()
    mutter("finished, %.3fu/%.3fs cpu, %.3fu/%.3fs cum, %.3f elapsed"
           % (times[:4] + ((times[4] - _starttime),)))



