# Copyright (C) 2009, 2010, 2011 Canonical Ltd
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


from StringIO import StringIO
import sys


import os


from bzrlib import (
    config,
    crash,
    osutils,
    symbol_versioning,
    tests,
    )

from bzrlib.tests import features


class TestApportReporting(tests.TestCaseInTempDir):

    _test_needs_features = [features.apport]

    def test_apport_report(self):
        crash_dir = osutils.joinpath((self.test_base_dir, 'crash'))
        os.mkdir(crash_dir)
        self.overrideEnv('APPORT_CRASH_DIR', crash_dir)
        self.assertEquals(crash_dir, config.crash_dir())

        stderr = StringIO()

        try:
            raise AssertionError("my error")
        except AssertionError, e:
            pass

        crash_filename = crash.report_bug_to_apport(sys.exc_info(),
            stderr)

        # message explaining the crash
        self.assertContainsRe(stderr.getvalue(),
            "    apport-bug %s" % crash_filename)

        crash_file = open(crash_filename)
        try:
            report = crash_file.read()
        finally:
            crash_file.close()

        self.assertContainsRe(report,
            '(?m)^BzrVersion:') # should be in the traceback
        self.assertContainsRe(report, 'my error')
        self.assertContainsRe(report, 'AssertionError')
        # see https://bugs.launchpad.net/bzr/+bug/528114
        self.assertContainsRe(report, 'ExecutablePath')
        self.assertContainsRe(report, 'test_apport_report')
        # should also be in there
        self.assertContainsRe(report, '(?m)^CommandLine:')
