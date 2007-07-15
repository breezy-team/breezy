# Copyright (C) 2007 Canonical Ltd
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

import sys

from bzrlib.builtins import cmd_cat
from bzrlib.tests import StringIOWrapper
from bzrlib.tests.TransportUtil import TestCaseWithConnectionHookedTransport

class TestCat(TestCaseWithConnectionHookedTransport):

    def setUp(self):
        super(TestCat, self).setUp()

        def restore_stdout():
            sys.stdout = self._stdout_orig

        # Redirect sys.stdout as this is what cat uses
        self.outf = StringIOWrapper()
        self._stdout_orig = sys.stdout
        sys.stdout = self.outf
        self.addCleanup(restore_stdout)

    def test_cat(self):
        wt1 = self.make_branch_and_tree('branch')
        file('branch/foo', 'wb').write('foo')
        wt1.add('foo')
        wt1.commit('add foo')

        self.install_hooks()
        self.addCleanup(self.reset_hooks)

        cmd = cmd_cat()
        cmd.run(self.get_url() + 'branch/foo')
        self.assertEquals(1, len(self.connections))
        self.assertEquals('foo', self.outf.getvalue())

