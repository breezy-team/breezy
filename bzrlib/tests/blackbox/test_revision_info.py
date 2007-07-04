# Copyright (C) 2004, 2005 Canonical Ltd
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

import os

from bzrlib.errors import BzrCommandError, NoSuchRevision
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestRevisionInfo(ExternalBase):
    
    def check_error(self, output, *args):
        """Verify that the expected error matches what bzr says.
        
        The output is supplied first, so that you can supply a variable
        number of arguments to bzr.
        """
        self.assertContainsRe(self.run_bzr(args, retcode=3)[1], output)

    def test_revision_info(self):
        """Test that 'bzr revision-info' reports the correct thing."""
        wt = self.make_branch_and_tree('.')

        # Make history with a non-mainline rev
        wt.commit('Commit one', rev_id='a@r-0-1')
        wt.commit('Commit two', rev_id='a@r-0-1.1.1')
        wt.set_parent_ids(['a@r-0-1', 'a@r-0-1.1.1'])
        wt.branch.set_last_revision_info(1, 'a@r-0-1')
        wt.commit('Commit three', rev_id='a@r-0-2')

        # This is expected to work even if the working tree is removed
        wt.bzrdir.destroy_workingtree()

        # Expected return values
        values = {
            '1'    : '   1 a@r-0-1\n',
            '1.1.1': '1.1.1 a@r-0-1.1.1\n',
            '2'    : '   2 a@r-0-2\n'
        }

        # Make sure with no arg it defaults to the head
        self.check_output(values['2'], 'revision-info')

        # Check the results of just specifying a numeric revision
        self.check_output(values['1'], 'revision-info', '1')
        self.check_output(values['1.1.1'], 'revision-info', '1.1.1')
        self.check_output(values['2'], 'revision-info', '2')
        self.check_output(values['1']+values['2'], 'revision-info', '1', '2')
        self.check_output(values['1']+values['1.1.1']+values['2'],
                          'revision-info', '1', '1.1.1', '2')
        self.check_output(values['2']+values['1'], 'revision-info', '2', '1')

        # Check as above, only using the '--revision' syntax
        
        self.check_output(values['1'], 'revision-info', '-r', '1')
        self.check_output(values['1.1.1'], 'revision-info', '--revision',
                          '1.1.1')
        self.check_output(values['2'], 'revision-info', '-r', '2')
        self.check_output(values['1']+values['2'], 'revision-info',
                          '-r', '1..2')
        self.check_output(values['1']+values['1.1.1']+values['2'],
                          'revision-info', '-r', '1..1.1.1..2')
        self.check_output(values['2']+values['1'], 'revision-info',
                          '-r', '2..1')

        # Now try some more advanced revision specifications
        
        self.check_output(values['1'], 'revision-info', '-r',
                          'revid:a@r-0-1')
        self.check_output(values['1.1.1'], 'revision-info', '--revision',
                          'revid:a@r-0-1.1.1')
