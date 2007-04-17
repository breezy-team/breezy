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

"""Blackbox tests for -D debug options"""

import os
import signal
import subprocess
import sys
import time

from bzrlib.tests import TestCase, TestSkipped

class TestDebugOption(TestCase):

    def test_dash_derror(self):
        """With -Derror, tracebacks are shown even for user errors"""
        out, err = self.run_bzr("-Derror", "branch", "nonexistent-location",
                retcode=3)
        # error output should contain a traceback; we used to look for code in
        # here but it may be missing if the source is not in sync with the
        # pyc file.
        self.assertContainsRe(err, "Traceback \\(most recent call last\\)")

class TestBreakin(TestCase):

    def test_breakin(self):
        # Break in to a debugger while bzr is running
        # we need to test against a command that will wait for 
        # a while -- bzr serve should do
        #
        # this may not work on windows but i don't think this use of signals
        # will work there
        if sys.platform == 'win32':
            raise TestSkipped('breakin signal not tested on win32')
        proc = self.start_bzr_subprocess(['serve'])
        time.sleep(.5)
        os.kill(proc.pid, signal.SIGQUIT)
        time.sleep(.5)
        proc.stdin.write('q\n')
        err = proc.stderr.read()
        self.assertContainsRe(err, r'entering debugger')
        proc.wait()
