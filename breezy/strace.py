# Copyright (C) 2007, 2009, 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Support for running strace against the current process."""

import os
import signal
import subprocess
import tempfile

from . import errors


def strace(function, *args, **kwargs):
    """Invoke strace on function.

    :return: a tuple: function-result, a StraceResult.
    """
    return strace_detailed(function, args, kwargs)


def strace_detailed(function, args, kwargs, follow_children=True):
    """Invoke strace on a function with detailed control over execution.

    This function runs strace on the given function, capturing system calls
    made during its execution. It provides more control than the basic
    strace() function, allowing configuration of fork following behavior.

    Args:
        function: The function to trace.
        args: Positional arguments to pass to the function.
        kwargs: Keyword arguments to pass to the function.
        follow_children: Whether strace should follow child processes.
            Default is True. Set to False to work around strace bugs
            when multiple threads are running.

    Returns:
        A tuple containing:
            - The result of calling function(*args, **kwargs)
            - A StraceResult object containing the strace log and error messages

    Raises:
        StraceError: If strace fails to attach to the process.
    """
    # FIXME: strace is buggy
    # (https://bugs.launchpad.net/ubuntu/+source/strace/+bug/103133) and the
    # test suite hangs if the '-f' is given to strace *and* more than one
    # thread is running. Using follow_children=False allows the test suite to
    # disable fork following to work around the bug.

    # capture strace output to a file
    log_file = tempfile.NamedTemporaryFile()
    err_file = tempfile.NamedTemporaryFile()
    pid = os.getpid()
    # start strace
    strace_cmd = ["strace", "-r", "-tt", "-p", str(pid), "-o", log_file.name]
    if follow_children:
        strace_cmd.append("-f")
    # need to catch both stdout and stderr to work around
    # bug 627208
    proc = subprocess.Popen(
        strace_cmd, stdout=subprocess.PIPE, stderr=err_file.fileno()
    )
    # Wait for strace to attach
    proc.stdout.readline()
    # Run the function to strace
    result = function(*args, **kwargs)
    # stop strace
    os.kill(proc.pid, signal.SIGQUIT)
    proc.communicate()
    # grab the log
    log_file.seek(0)
    log = log_file.read()
    log_file.close()
    # and stderr
    err_file.seek(0)
    err_messages = err_file.read()
    err_file.close()
    # and read any errors
    if err_messages.startswith("attach: ptrace(PTRACE_ATTACH,"):
        raise StraceError(err_messages=err_messages)
    return result, StraceResult(log, err_messages)


class StraceError(errors.BzrError):
    """Error raised when strace fails to attach to a process.

    This error is raised when strace cannot attach to the current process,
    typically due to permission issues or system configuration restrictions.
    """

    _fmt = "strace failed: %(err_messages)s"


class StraceResult:
    """The result of stracing a function."""

    def __init__(self, raw_log, err_messages):
        """Create a StraceResult.

        :param raw_log: The output that strace created.
        """
        self.raw_log = raw_log
        self.err_messages = err_messages
