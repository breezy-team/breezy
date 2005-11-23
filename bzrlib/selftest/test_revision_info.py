# Copyright (C) 2004, 2005 by Canonical Ltd

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

import os
from bzrlib.selftest import TestCaseInTempDir
from bzrlib.errors import BzrCommandError, NoSuchRevision
from bzrlib.branch import Branch
from bzrlib.revisionspec import RevisionSpec

class TestRevisionInfo(TestCaseInTempDir):
    
    def check_error(self, output, *args):
        """Verify that the expected error matches what bzr says.
        
        The output is supplied first, so that you can supply a variable
        number of arguments to bzr.
        """
        self.assertContainsRe(self.run_bzr_captured(args, retcode=3)[1], output)

    def check_output(self, output, *args):
        """Verify that the expected output matches what bzr says.
        
        The output is supplied first, so that you can supply a variable
        number of arguments to bzr.
        """
        self.assertEquals(self.run_bzr_captured(args)[0], output)

    def test_revision_info(self):
        """Test that 'bzr revision-info' reports the correct thing.
        """

        b = Branch.initialize('.')

        b.working_tree().commit('Commit one', rev_id='a@r-0-1')
        b.working_tree().commit('Commit two', rev_id='a@r-0-2')
        b.working_tree().commit('Commit three', rev_id='a@r-0-3')

        # Make sure revision-info without any arguments throws an exception
        self.check_error('bzr: ERROR: bzrlib.errors.BzrCommandError: '
                         'You must supply a revision identifier\n',
                         'revision-info')

        values = {
            1:'   1 a@r-0-1\n',
            2:'   2 a@r-0-2\n',
            3:'   3 a@r-0-3\n'
        }

        # Check the results of just specifying a numeric revision
        self.check_output(values[1], 'revision-info', '1')
        self.check_output(values[2], 'revision-info', '2')
        self.check_output(values[3], 'revision-info', '3')
        self.check_output(values[1]+values[2], 'revision-info', '1', '2')
        self.check_output(values[1]+values[2]+values[3], 'revision-info', '1', '2', '3')
        self.check_output(values[2]+values[1], 'revision-info', '2', '1')

        # Check as above, only using the '--revision' syntax
        
        self.check_output('   1 a@r-0-1\n', 'revision-info', '-r', '1')
        self.check_output('   2 a@r-0-2\n', 'revision-info', '--revision', '2')
        self.check_output('   3 a@r-0-3\n', 'revision-info', '-r', '3')
        self.check_output('   1 a@r-0-1\n   2 a@r-0-2\n', 'revision-info', '-r', '1..2')
        self.check_output('   1 a@r-0-1\n   2 a@r-0-2\n   3 a@r-0-3\n'
                , 'revision-info', '-r', '1..2..3')
        self.check_output('   2 a@r-0-2\n   1 a@r-0-1\n', 'revision-info', '-r', '2..1')

        # Now try some more advanced revision specifications
        
        self.check_output('   1 a@r-0-1\n', 'revision-info', '-r', 'revid:a@r-0-1')
        self.check_output('   2 a@r-0-2\n', 'revision-info', '--revision', 'revid:a@r-0-2')

    def test_cat_revision(self):
        """Test bzr cat-revision.
        """
        b = Branch.initialize('.')

        b.working_tree().commit('Commit one', rev_id='a@r-0-1')
        b.working_tree().commit('Commit two', rev_id='a@r-0-2')
        b.working_tree().commit('Commit three', rev_id='a@r-0-3')

        revs = {
            1:b.get_revision_xml('a@r-0-1'),
            2:b.get_revision_xml('a@r-0-2'),
            3:b.get_revision_xml('a@r-0-3')
        }

        self.check_output(revs[1], 'cat-revision', 'a@r-0-1')
        self.check_output(revs[2], 'cat-revision', 'a@r-0-2')
        self.check_output(revs[3], 'cat-revision', 'a@r-0-3')

        self.check_output(revs[1], 'cat-revision', '-r', '1')
        self.check_output(revs[2], 'cat-revision', '-r', '2')
        self.check_output(revs[3], 'cat-revision', '-r', '3')

        self.check_output(revs[1], 'cat-revision', '-r', 'revid:a@r-0-1')
        self.check_output(revs[2], 'cat-revision', '-r', 'revid:a@r-0-2')
        self.check_output(revs[3], 'cat-revision', '-r', 'revid:a@r-0-3')

