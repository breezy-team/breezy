# Copyright (C) 2005 by Canonical Ltd
# -*- coding: utf-8 -*-

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


"""Black-box tests for bzr.

These check that it behaves properly when it's invoked through the regular
command-line interface. This doesn't actually run a new interpreter but 
rather starts again from the run_bzr function.
"""

from bzrlib.tests import TestLoader
from bzrlib.tests import TestCaseInTempDir, BzrTestBase

def test_suite():
    testmod_names = [
                     'bzrlib.tests.blackbox.test_cat',
                     'bzrlib.tests.blackbox.test_export',
                     'bzrlib.tests.blackbox.test_log',
                     'bzrlib.tests.blackbox.test_missing',
                     'bzrlib.tests.blackbox.test_pull',
                     'bzrlib.tests.blackbox.test_revno',
                     'bzrlib.tests.blackbox.test_revision_info',
                     'bzrlib.tests.blackbox.test_status',
                     'bzrlib.tests.blackbox.test_too_much',
                     'bzrlib.tests.blackbox.test_versioning',
                     ]
    return TestLoader().loadTestsFromNames(testmod_names)


class ExternalBase(TestCaseInTempDir):

    def runbzr(self, args, retcode=0, backtick=False):
        if isinstance(args, basestring):
            args = args.split()
        if backtick:
            return self.run_bzr_captured(args, retcode=retcode)[0]
        else:
            return self.run_bzr_captured(args, retcode=retcode)
