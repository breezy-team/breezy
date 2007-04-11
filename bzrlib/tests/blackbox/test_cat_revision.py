# Copyright (C) 2004, 2005, 2007 Canonical Ltd
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

from bzrlib.tests import blackbox


class TestCatRevision(blackbox.ExternalBase):

    def test_cat_unicode_revision(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('This revision', rev_id='abcd')
        output, errors = self.run_bzr('cat-revision', u'abcd')
        self.assertContainsRe(output, 'This revision')
        self.assertEqual('', errors)

    def test_cat_revision(self):
        """Test bzr cat-revision.
        """
        wt = self.make_branch_and_tree('.')
        r = wt.branch.repository

        wt.commit('Commit one', rev_id='a@r-0-1')
        wt.commit('Commit two', rev_id='a@r-0-2')
        wt.commit('Commit three', rev_id='a@r-0-3')

        revs = {
            1:r.get_revision_xml('a@r-0-1'),
            2:r.get_revision_xml('a@r-0-2'),
            3:r.get_revision_xml('a@r-0-3'),
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
