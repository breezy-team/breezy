# Copyright (C) 2006, 2007, 2009 Canonical Ltd
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

"""Blackbox tests for debugger breakin"""

try:
    import ctypes
    have_ctypes = True
except ImportError:
    have_ctypes = False
import errno
import os
import signal
import subprocess
import sys
import time

from bzrlib import (
    breakin,
    errors,
    tests,
    )


class TestBreakin(tests.TestCase):
    # FIXME: If something is broken, these tests may just hang indefinitely in
    # wait() waiting for the child to exit when it's not going to.

    def setUp(self):
        super(TestBreakin, self).setUp()
        if breakin.determine_signal() is None:
            raise tests.TestSkipped('this platform is missing SIGQUIT'
                                    ' or SIGBREAK')
        if sys.platform == 'win32':
            # Windows doesn't have os.kill, and we catch the SIGBREAK signal.
            # We trigger SIGBREAK via a Console api so we need ctypes to access
            # the function
            if not have_ctypes:
                raise tests.UnavailableFeature('ctypes')
            self._send_signal = self._send_signal_win32
        else:
            self._send_signal = self._send_signal_via_kill

    def _send_signal_via_kill(self, pid, sig_type):
        if sig_type == 'break':
            sig_num = signal.SIGQUIT
        elif sig_type == 'kill':
            sig_num = signal.SIGKILL
        else:
            raise ValueError("unknown signal type: %s" % (sig_type,))
        os.kill(pid, sig_num)

    def _send_signal_win32(self, pid, sig_type):
        """Send a 'signal' on Windows.

        Windows doesn't really have signals in the same way. All it really
        supports is:
            1) Sending SIGINT to the *current* process group (so self, and all
                children of self)
            2) Sending SIGBREAK to a process that shares the current console,
                which can be in its own process group.
        So we have start_bzr_subprocess create a new process group for the
        spawned process (via a flag to Popen), and then we map
            SIGQUIT to GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT)
            SIGKILL to TerminateProcess
        """
        if sig_type == 'break':
            CTRL_BREAK_EVENT = 1
            # CTRL_C_EVENT = 0
            ret = ctypes.windll.kernel32.GenerateConsoleCtrlEvent(
                    CTRL_BREAK_EVENT, pid)
            if ret == 0: #error
                err = ctypes.FormatError()
                raise RuntimeError('failed to send CTRL_BREAK: %s'
                                   % (err,))
        elif sig_type == 'kill':
            # Does the exit code matter? For now we are just setting it to
            # something other than 0
            exit_code = breakin.determine_signal()
            ctypes.windll.kernel32.TerminateProcess(pid, exit_code)

    def _popen(self, *args, **kwargs):
        if sys.platform == 'win32':
            CREATE_NEW_PROCESS_GROUP = 512
            # This allows us to send a signal to the child, *without* also
            # sending it to ourselves
            kwargs['creationflags'] = CREATE_NEW_PROCESS_GROUP
        return super(TestBreakin, self)._popen(*args, **kwargs)

    def _dont_SIGQUIT_on_darwin(self):
        if sys.platform == 'darwin':
            # At least on Leopard and with python 2.6, this test will raise a
            # popup window asking if the python failure should be reported to
            # Apple... That's not the point of the test :) Marking the test as
            # not applicable Until we find a way to disable that intrusive
            # behavior... --vila20080611
            raise tests.TestNotApplicable(
                '%s raises a popup on OSX' % self.id())

    def _wait_for_process(self, pid, sig=None):
        # We don't know quite how long waiting for the process 'pid' will take,
        # but if it's more than 10s then it's probably not going to work.
        for i in range(100):
            time.sleep(0.1)
            if sig is not None:
                self._send_signal(pid, sig)
            # Use WNOHANG to ensure we don't get blocked, doing so, we may
            # leave the process continue after *we* die...
            # Win32 doesn't support WNOHANG, so we just pass 0
            opts = getattr(os, 'WNOHANG', 0)
            try:
                # TODO: waitpid doesn't work well on windows, we might consider
                #       using WaitForSingleObject(proc._handle, TIMEOUT)
                #       instead. Most notably, the WNOHANG isn't allowed, so
                #       this can hang indefinitely.
                pid_killed, returncode = os.waitpid(pid, opts)
                if (pid_killed, returncode) != (0, 0):
                    if sig is not None:
                        # high bit in low byte says if core was dumped; we
                        # don't care
                        status, sig = (returncode >> 8, returncode & 0x7f)
                        return True, sig
            except OSError, e:
                if e.errno in (errno.ECHILD, errno.ESRCH):
                    # The process doesn't exist anymore
                    return True, None
                else:
                    raise

        return False, None

    # port 0 means to allocate any port
    _test_process_args = ['serve', '--port', 'localhost:0']

    def test_breakin(self):
        # Break in to a debugger while bzr is running
        # we need to test against a command that will wait for
        # a while -- bzr serve should do
        proc = self.start_bzr_subprocess(self._test_process_args,
                env_changes=dict(BZR_SIGQUIT_PDB=None))
        # wait for it to get started, and print the 'listening' line
        proc.stderr.readline()
        # first sigquit pops into debugger
        self._send_signal(proc.pid, 'break')
        # Wait for the debugger to acknowledge the signal reception
        # Note that it is possible for this to deadlock if the child doesn't
        # acknowlege the signal and write to stderr. Perhaps we should try
        # os.read(proc.stderr.fileno())?
        err = proc.stderr.readline()
        self.assertContainsRe(err, r'entering debugger')
        # Now that the debugger is entered, we can ask him to quit
        proc.stdin.write("q\n")
        # We wait a bit to let the child process handles our query and avoid
        # triggering deadlocks leading to hangs on multi-core hosts...
        dead, sig = self._wait_for_process(proc.pid)
        if not dead:
            # The process didn't finish, let's kill it before reporting failure
            dead, sig = self._wait_for_process(proc.pid, 'kill')
            if dead:
                raise tests.KnownFailure(
                    "subprocess wasn't terminated, it had to be killed")
            else:
                self.fail("subprocess %d wasn't terminated by repeated SIGKILL",
                          proc.pid)

    def test_breakin_harder(self):
        """SIGQUITting twice ends the process."""
        self._dont_SIGQUIT_on_darwin()
        proc = self.start_bzr_subprocess(self._test_process_args,
                env_changes=dict(BZR_SIGQUIT_PDB=None))
        # wait for it to get started, and print the 'listening' line
        proc.stderr.readline()
        # break into the debugger
        self._send_signal(proc.pid, 'break')
        # Wait for the debugger to acknowledge the signal reception (since we
        # want to send a second signal, we ensure it doesn't get lost by
        # validating the first get received and produce its effect).
        err = proc.stderr.readline()
        self.assertContainsRe(err, r'entering debugger')
        dead, sig = self._wait_for_process(proc.pid, 'break')
        self.assertTrue(dead)
        # Either the child was dead before we could read its status, or the
        # child was dead from the signal we sent it.
        self.assertTrue(sig in (None, breakin.determine_signal()))

    def test_breakin_disabled(self):
        self._dont_SIGQUIT_on_darwin()
        proc = self.start_bzr_subprocess(self._test_process_args,
                env_changes=dict(BZR_SIGQUIT_PDB='0'))
        # wait for it to get started, and print the 'listening' line
        proc.stderr.readline()
        # first hit should just kill it
        self._send_signal(proc.pid, 'break')
        proc.wait()
