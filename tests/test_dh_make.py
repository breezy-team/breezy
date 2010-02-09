import tarfile

from bzrlib.plugins.builddeb import dh_make
from bzrlib.plugins.builddeb.tests import BuilddebTestCase


class dh_makeTests(BuilddebTestCase):

    def test__get_tree_existing_branch(self):
        tree = self.make_branch_and_tree('.')
        new_tree = dh_make._get_tree("foo")
        self.failIfExists("foo")
        self.assertEqual(tree.branch.base, new_tree.branch.base)

    # Can't test creating a new tree as bzr's test suite puts us
    # inside a tree

    def test_import_upstream(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        tree.add(['a'])
        revid = tree.commit("one")
        self.build_tree(['package-0.1/', 'package-0.1/a', 'package-0.1/b'])
        tf = tarfile.open('package-0.1.tar.gz', 'w:gz')
        try:
            tf.add('package-0.1')
        finally:
            tf.close()
        new_tree = dh_make.import_upstream('package-0.1', 'package', '0.1')
        self.assertEqual(tree.branch.base, new_tree.branch.base)
        self.assertNotEqual(revid, tree.branch.last_revision())
        rev_tree = tree.branch.repository.revision_tree(
                tree.branch.last_revision())
        # Has the original revision as a parent
        self.assertEqual([revid], rev_tree.get_parent_ids())
        self.failUnlessExists('a')
        self.failUnlessExists('b')
        self.assertEqual(open('package-0.1/a').read(), open('a').read())
