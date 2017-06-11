from __future__ import absolute_import

import tarfile

from .. import dh_make
from . import BuilddebTestCase


class dh_makeTests(BuilddebTestCase):

    def test__get_tree_existing_branch(self):
        tree = self.make_branch_and_tree('.')
        new_tree = dh_make._get_tree("foo")
        self.assertPathDoesNotExist("foo")
        self.assertEqual(tree.branch.base, new_tree.branch.base)

    def test__get_tree_no_existing_branch(self):
        new_tree = dh_make._get_tree("foo")
        self.assertPathExists("foo")

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
        self.assertPathExists('a')
        self.assertPathExists('b')
        self.assertEqual(open('package-0.1/a').read(), open('a').read())
        self.assertPathExists('../package_0.1.orig.tar.gz')

    def test_import_upstream_no_existing(self):
        self.build_tree(['package-0.1/', 'package-0.1/a', 'package-0.1/b'])
        tf = tarfile.open('package-0.1.tar.gz', 'w:gz')
        try:
            tf.add('package-0.1')
        finally:
            tf.close()
        tree = dh_make.import_upstream('package-0.1', 'package', '0.1')
        self.assertPathExists("package")
        rev_tree = tree.branch.repository.revision_tree(
                tree.branch.last_revision())
        # Has the original revision as a parent
        self.assertPathExists('package/a')
        self.assertPathExists('package/b')
        self.assertEqual(open('package-0.1/a').read(),
               open('package/a').read())
        self.assertPathExists('package_0.1.orig.tar.gz')
