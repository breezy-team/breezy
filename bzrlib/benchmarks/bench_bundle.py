# Copyright (C) 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for bzr bundle performance."""

from cStringIO import StringIO
import os
import shutil

from bzrlib import bzrdir
from bzrlib.add import smart_add
from bzrlib.benchmarks import Benchmark
from bzrlib.branch import Branch
from bzrlib.bundle import read_bundle
from bzrlib.bundle.apply_bundle import install_bundle
from bzrlib.bundle.serializer import write_bundle
from bzrlib.revision import NULL_REVISION
from bzrlib.revisionspec import RevisionSpec
from bzrlib.workingtree import WorkingTree


class BundleBenchmark(Benchmark):
    """Benchmarks for bzr bundle performance and bzr merge with a bundle."""
   
    def test_create_bundle_known_kernel_like_tree(self):
        """Create a bundle for a kernel sized tree with no ignored, unknowns,
        or added and one commit.
        """ 
        self.make_kernel_like_committed_tree()
        self.time(self.run_bzr, 'bundle', '--revision', '..-1')

    def test_create_bundle_many_commit_tree (self):
        """Create a bundle for a tree with many commits but no changes.""" 
        self.make_many_commit_tree()
        self.time(self.run_bzr, 'bundle', '--revision', '..-1')

    def test_create_bundle_heavily_merged_tree(self):
        """Create a bundle for a heavily merged tree.""" 
        self.make_heavily_merged_tree()
        self.time(self.run_bzr, 'bundle', '--revision', '..-1')
        
    def test_apply_bundle_known_kernel_like_tree(self):
        """Create a bundle for a kernel sized tree with no ignored, unknowns,
        or added and one commit.
        """ 
        tree = self.make_kernel_like_tree_committed('tree')

        f = open('bundle', 'wb')
        try:
            write_bundle(tree.branch.repository, tree.last_revision(),
                         NULL_REVISION, f)
        finally:
            f.close()

        tree2 = self.make_branch_and_tree('branch_a')
        os.chdir('branch_a')
        self.time(self.run_bzr, 'merge', '../bundle')
 
class BundleLibraryLevelWriteBenchmark(Benchmark):
    """ Benchmarks for the write_bundle library function. """

    def _time_read_write(self):
        print "timing"
        branch, relpath = Branch.open_containing("a")
        revision_history = branch.revision_history()
        bundle_text = StringIO()
        print "starting write bundle"
        self.time(write_bundle, branch.repository, revision_history[-1],
                  NULL_REVISION, bundle_text)
        print "stopped writing bundle"
        bundle_text.seek(0)
        target_tree = self.make_branch_and_tree('b')
        print "starting reading bundle"
        bundle = self.time(read_bundle, bundle_text)
        print "starting installing bundle"
        self.time(install_bundle, target_tree.branch.repository, bundle)

    def test_few_files_small_tree_1_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(5, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:5], 1, 1)
        self._time_read_write()

    def test_few_files_small_tree_500_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(5, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:5], 500, 1)
        self._time_read_write()

    def test_few_files_small_tree_1000_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(5, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:5], 1000, 1)
        self._time_read_write()

    def test_few_files_moderate_tree_1_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:5], 1, 1)
        self._time_read_write()

    def test_few_files_moderate_tree_500_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:5], 500, 1)
        self._time_read_write()

    def test_few_files_moderate_tree_1000_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:5], 1000, 1)
        self._time_read_write()

    def test_some_files_moderate_tree_1_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:100], 1, 1)
        self._time_read_write()

    def test_some_files_moderate_tree_500_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:100], 500, 1)
        self._time_read_write()

    def test_some_files_moderate_tree_1000_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:100], 1000, 1)
        self._time_read_write()

    def test_few_files_big_tree_1_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(1000, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:5], 1, 1)
        self._time_read_write()

    def test_few_files_big_tree_500_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(1000, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:5], 500, 1)
        self._time_read_write()

    def test_few_files_big_tree_1000_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(1000, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:5], 1000, 1)
        self._time_read_write()

    def test_some_files_big_tree_1_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(1000, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:100], 1, 1)
        self._time_read_write()

    def test_some_files_big_tree_500_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(1000, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:100], 500, 1)
        self._time_read_write()

    def test_some_files_big_tree_1000_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(1000, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:100], 1000, 1)
        self._time_read_write()

    def test_many_files_big_tree_1_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(1000, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:1000], 1, 1)
        self._time_read_write()

    def test_many_files_big_tree_500_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(1000, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:1000], 500, 1)
        self._time_read_write()

    def test_many_files_big_tree_1000_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(1000, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:1000], 1000, 1)
        self._time_read_write()


if __name__ == '__main__':
    # USE the following if you want to regenerate the above test functions 
    for treesize, treesize_h in [(5, "small"), (100, "moderate"),
                                 (1000, "big")]:
        for bundlefiles, bundlefiles_h in [(5, "few"), (100, "some"),
                                           (1000, "many")]:
            if bundlefiles > treesize:
                continue
            for num_revisions in [1, 500, 1000]:
                code = """\
    def test_%s_files_%s_tree_%s_revision(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(%s, 1, directory_name="a")
        self.commit_some_revisions(tree, files[:%s], %s, 1)
        self._time_read_write()
""" % (bundlefiles_h, treesize_h, num_revisions,
       treesize, bundlefiles, num_revisions)
                print code


