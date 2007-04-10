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
