#    test_merge_package.py -- Merge packaging branches, fix ancestry as needed.
#    Copyright (C) 2008 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import os
import unittest

from debian_bundle.changelog import Version
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree


class MergePackageTests(TestCaseWithTransport):

    def set_file_content(self, path, content):
        f = open(path, 'wb')
        try:
            f.write(content)
        finally:
            f.close()

    def test_debian_upstream_newer(self):
        # Set up debian upstream branch.
        debu_tree = self.make_branch_and_tree('debu', format='dirstate-tags')
        self.build_tree(['debu/a'])
        debu_tree.add(['a'], ['a-id'])
        revid_debu_A = debu_tree.commit('add a', rev_id='du-1')
        debu_tree.branch.tags.set_tag('[debu-A]', revid_debu_A)

        self.build_tree(['debu/b'])
        debu_tree.add(['b'], ['b-id'])
        revid_debu_B = debu_tree.commit('add b', rev_id='du-2')
        debu_tree.branch.tags.set_tag('[debu-B]', revid_debu_B)

        self.build_tree(['debu/h'])
        debu_tree.add(['h'], ['h-id'])
        self.build_tree_contents(
            [('debu/b', 'Debian upstream contents for b\n')])
        revid_debu_H = debu_tree.commit('add h', rev_id='du-3')
        debu_tree.branch.tags.set_tag('[debu-H]', revid_debu_H)

        # Set up ubuntu upstream branch.
        ubuu_tree = debu_tree.bzrdir.sprout(
            'ubuu', revision_id=revid_debu_B).open_workingtree()

        self.build_tree_contents(
            [('ubuu/b', 'Ubuntu upstream contents for b\n')])
        revid_ubuu_G = ubuu_tree.commit('modifying b', rev_id='uu-3')
        ubuu_tree.branch.tags.set_tag('[ubuu-G]', revid_ubuu_G)

        # Set up debian packaging branch.
        debp_tree = self.make_branch_and_tree('debp', format='dirstate-tags')
        debp_tree.pull(debu_tree.branch, stop_revision=revid_debu_A)

        self.build_tree(['debp/debian/', 'debp/debian/changelog'])
        self.build_tree_contents(
            [('debp/debian/changelog', 'debp changelog, rev. D\n')])
        debp_tree.merge_from_branch(debu_tree.branch, to_revision=revid_debu_B)
        revid_debp_D = debp_tree.commit('add debian/changelog', rev_id='dp-1')
        debp_tree.branch.tags.set_tag('[debp-D]', revid_debp_D)

        self.build_tree_contents(
            [('debp/debian/changelog', 'debp changelog, rev. D\ndebp changelog, rev. J\n')])
        debp_tree.merge_from_branch(debu_tree.branch, to_revision=revid_debu_H)
        revid_debp_J = debp_tree.commit('modified debian/changelog', rev_id='dp-2')
        debp_tree.branch.tags.set_tag('[debp-J]', revid_debp_J)

        # Set up ubuntu packaging branch.
        ubup_tree = self.make_branch_and_tree('ubup', format='dirstate-tags')
        ubup_tree.pull(debu_tree.branch, stop_revision=revid_debu_A)

        self.build_tree(['ubup/debian/', 'ubup/debian/changelog'])
        self.build_tree_contents(
            [('ubup/debian/changelog', 'ubup changelog, rev. E\n')])
        revid_ubup_E = ubup_tree.commit('add debian/changelog', rev_id='up-1')
        ubup_tree.branch.tags.set_tag('[ubup-E]', revid_ubup_E)

        self.build_tree_contents(
            [('ubup/debian/changelog', 'ubup changelog, rev. E\nubup changelog, rev. F\n')])
        revid_ubup_F = ubup_tree.commit('modified debian/changelog', rev_id='up-2')
        ubup_tree.branch.tags.set_tag('[ubup-F]', revid_ubup_F)

        self.build_tree_contents(
            [('ubup/debian/changelog', 'ubup changelog, rev. E\nubup changelog, rev. F\nubup changelog, rev. I\n')])
        ubup_tree.merge_from_branch(ubuu_tree.branch, to_revision=revid_ubuu_G)
        revid_ubup_I = ubup_tree.commit('modified debian/changelog', rev_id='up-3')
        ubup_tree.branch.tags.set_tag('[ubup-I]', revid_ubup_I)

        import pdb
        pdb.set_trace()


def suite():
    suite = unittest.TestSuite()
    suite.addTest(MergePackageTests('test_shared_ancestry'))
    return suite

if __name__ == '__main__':
    unittest.main()
    #results = unittest.TestResult()
    #suite().run(results)
    #print results

