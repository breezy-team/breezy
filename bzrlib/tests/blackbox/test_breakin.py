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

"""Blackbox tests for debugger breakin"""

import os
import signal
import subprocess
import sys
import time

from bzrlib import tests


class TestBreakin(tests.TestCase):
    # FIXME: If something is broken, these tests may just hang indefinitely in
    # wait() waiting for the child to exit when it's not going to.

    def setUp(self):
        if sys.platform == 'win32':
            raise tests.TestSkipped('breakin signal not tested on win32')
        super(TestBreakin, self).setUp()

    def _dont_SIGQUIT_on_darwin(self):
        if sys.platform == 'darwin':
            # At least on Leopard and with python 2.6, this test will raise a
            # popup window asking if the python failure should be reported to
            # Apple... That's not the point of the test :) Marking the test as
            # not applicable Until we find a way to disable that intrusive
            # behavior... --vila20080611
            raise tests.TestNotApplicable(
                '%s raises a popup on OSX' % self.id())

    # port 0 means to allocate any port
    _test_process_args = ['serve', '--port', 'localhost:0']

    def test_breakin(self):
        # Break in to a debugger while bzr is running
        # we need to test against a command that will wait for 
        # a while -- bzr serve should do
        proc = self.start_bzr_subprocess(self._test_process_args,
                env_changes=dict(BZR_SIGQUIT_PDB=None))
        # wait for it to get started, and print the 'listening' line
        proc.stdout.readline()
        # first sigquit pops into debugger
        os.kill(proc.pid, signal.SIGQUIT)
        proc.stdin.write("q\n")
        time.sleep(.5)
        err = proc.stderr.readline()
        self.assertContainsRe(err, r'entering debugger')

    def test_breakin_harder(self):
        self._dont_SIGQUIT_on_darwin()
        proc = self.start_bzr_subprocess(self._test_process_args,
                env_changes=dict(BZR_SIGQUIT_PDB=None))
        # wait for it to get started, and print the 'listening' line
        proc.stdout.readline()
        # break into the debugger
        os.kill(proc.pid, signal.SIGQUIT)
        # now send a second sigquit, which should cause it to exit.  That
        # won't happen until the original signal has been noticed by the
        # child and it's run its signal handler.  We don't know quite how long
        # this will take, but if it's more than 10s then it's probably not
        # going to work.
        for i in range(100):
            time.sleep(0.1)
            os.kill(proc.pid, signal.SIGQUIT)
            # note: waitpid is different on win32, but this test only runs on
            # unix
            r = os.waitpid(proc.pid, os.WNOHANG)
            if r != (0, 0):
                # high bit says if core was dumped; we don't care
                self.assertEquals(r[1] & 0x7f, signal.SIGQUIT)
                break
        else:
            self.fail("subprocess wasn't terminated by repeated SIGQUIT")

    def test_breakin_disabled(self):
        self._dont_SIGQUIT_on_darwin()
        proc = self.start_bzr_subprocess(self._test_process_args,
                env_changes=dict(BZR_SIGQUIT_PDB='0'))
        # wait for it to get started, and print the 'listening' line
        proc.stdout.readline()
        # first hit should just kill it
        os.kill(proc.pid, signal.SIGQUIT)
        proc.wait()
