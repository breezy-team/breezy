# Copyright (C) 2007 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Support for running strace against the current process."""

import os
import signal
import subprocess
import tempfile

# this is currently test-focused, so importing bzrlib.tests is ok. We might
# want to move feature to its own module though.
from bzrlib.tests import Feature

def strace(function, *args, **kwargs):
    """Invoke strace on function.

    :return: A StraceResult.
    """
    # capture strace output to a file
    log_file = tempfile.TemporaryFile()
    log_file_fd = log_file.fileno()
    pid = os.getpid()
    # start strace
    proc = subprocess.Popen(['strace',
        '-f', '-r', '-tt', '-p', str(pid),
        ],
        stderr=log_file_fd,
        stdout=log_file_fd)
    # TODO? confirm its started (test suite should be sufficient)
    # (can loop on proc.pid, but that may not indicate started and attached.)
    function(*args, **kwargs)
    # stop strace
    os.kill(proc.pid, signal.SIGQUIT)
    proc.communicate()
    # grab the log
    log_file.seek(0)
    log = log_file.read()
    log_file.close()
    return StraceResult(log)


class StraceResult(object):
    """The result of stracing a function."""

    def __init__(self, raw_log):
        """Create a StraceResult.

        :param raw_log: The output that strace created.
        """
        self.raw_log = raw_log


class _StraceFeature(Feature):

    def _probe(self):
        try:
            proc = subprocess.Popen(['strace'],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE)
            proc.communicate()
            return True
        except OSError, e:
            if e.errno == errno.ENOENT:
                # strace is not installed
                return False
            else:
                raise

    def feature_name(self):
        return 'strace'

StraceFeature = _StraceFeature()
