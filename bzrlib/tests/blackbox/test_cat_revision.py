from bzrlib import tests

class TestCatRevision(tests.TestCaseWithTransport):

    def test_cat_revision(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('This revision', rev_id='abcd')
        output, errors = self.run_bzr('cat-revision', u'abcd')
        self.assertContainsRe(output, 'This revision')
        self.assertEqual('', errors)
