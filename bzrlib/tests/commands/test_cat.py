# Copyright (C) 2007, 2009, 2010, 2016 Canonical Ltd
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

import sys

from bzrlib.builtins import cmd_cat
from bzrlib.tests import StringIOWrapper
from bzrlib.tests.transport_util import TestCaseWithConnectionHookedTransport


class TestCat(TestCaseWithConnectionHookedTransport):

    def setUp(self):
        super(TestCat, self).setUp()
        # Redirect sys.stdout as this is what cat uses
        self.outf = StringIOWrapper()
        self.overrideAttr(sys, 'stdout', self.outf)

    def test_cat(self):
        # FIXME: sftp raises ReadError instead of NoSuchFile when probing for
        # branch/foo/.bzr/branch-format when used with the paramiko test
        # server.
        from bzrlib.tests import TestSkipped
        raise TestSkipped('SFTPTransport raises incorrect exception'
                          ' when reading from paramiko server')
        wt1 = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/foo', 'foo')])
        wt1.add('foo')
        wt1.commit('add foo')

        self.start_logging_connections()

        cmd = cmd_cat()
        cmd.run(self.get_url('branch/foo'))
        self.assertEqual(1, len(self.connections))
        self.assertEqual('foo', self.outf.getvalue())

