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
    def test_revision_info(self):
        """Test that 'bzr revision-info' reports the correct thing.
        """

        b = Branch.initialize('.')

        b.commit('Commit one', rev_id='a@r-0-1')
        b.commit('Commit two', rev_id='a@r-0-2')
        b.commit('Commit three', rev_id='a@r-0-3')

        def check(output, *args):
            """Verify that the expected output matches what bzr says.
            
            The output is supplied first, so that you can supply a variable
            number of arguments to bzr.
            """
            self.assertEquals(self.backtick(['bzr'] + list(args)), output)

        # Make sure revision-info without any arguments throws an exception
        self.assertRaises(BzrCommandError, self.run_bzr, 'revision-info')

        values = {
            1:'   1 a@r-0-1\n',
            2:'   2 a@r-0-2\n',
            3:'   3 a@r-0-3\n'
        }

        # Check the results of just specifying a numeric revision
        check(values[1], 'revision-info', '1')
        check(values[2], 'revision-info', '2')
        check(values[3], 'revision-info', '3')
        check(values[1]+values[2], 'revision-info', '1', '2')
        check(values[1]+values[2]+values[3], 'revision-info', '1', '2', '3')
        check(values[2]+values[1], 'revision-info', '2', '1')

        # Check as above, only using the '--revision' syntax
        
        check('   1 a@r-0-1\n', 'revision-info', '-r', '1')
        check('   2 a@r-0-2\n', 'revision-info', '--revision', '2')
        check('   3 a@r-0-3\n', 'revision-info', '-r', '3')
        check('   1 a@r-0-1\n   2 a@r-0-2\n', 'revision-info', '-r', '1..2')
        check('   1 a@r-0-1\n   2 a@r-0-2\n   3 a@r-0-3\n'
                , 'revision-info', '-r', '1..2..3')
        check('   2 a@r-0-2\n   1 a@r-0-1\n', 'revision-info', '-r', '2..1')

        # Now try some more advanced revision specifications
        
        check('   1 a@r-0-1\n', 'revision-info', '-r', 'revid:a@r-0-1')
        check('   2 a@r-0-2\n', 'revision-info', '--revision', 'revid:a@r-0-2')

    def test_cat_revision(self):
        """Test bzr cat-revision.
        """
        b = Branch.initialize('.')

        b.commit('Commit one', rev_id='a@r-0-1')
        b.commit('Commit two', rev_id='a@r-0-2')
        b.commit('Commit three', rev_id='a@r-0-3')

        revs = {
            1:b.get_revision_xml_file('a@r-0-1').read(),
            2:b.get_revision_xml_file('a@r-0-2').read(),
            3:b.get_revision_xml_file('a@r-0-3').read()
        }

        def check(output, *args):
            self.assertEquals(self.backtick(['bzr'] + list(args)), output)

        check(revs[1], 'cat-revision', 'a@r-0-1')
        check(revs[2], 'cat-revision', 'a@r-0-2')
        check(revs[3], 'cat-revision', 'a@r-0-3')

        check(revs[1], 'cat-revision', '-r', '1')
        check(revs[2], 'cat-revision', '-r', '2')
        check(revs[3], 'cat-revision', '-r', '3')

        check(revs[1], 'cat-revision', '-r', 'revid:a@r-0-1')
        check(revs[2], 'cat-revision', '-r', 'revid:a@r-0-2')
        check(revs[3], 'cat-revision', '-r', 'revid:a@r-0-3')

