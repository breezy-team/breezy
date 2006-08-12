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


import os
import shutil
from StringIO import StringIO

from bzrlib.benchmarks import Benchmark
from bzrlib.workingtree import WorkingTree
from bzrlib.branch import Branch
from bzrlib.bundle.serializer import write_bundle
from bzrlib.bundle import read_bundle
from bzrlib.revisionspec import RevisionSpec

# if set, creation of test trees will be globally cached (even across test runs)
#CACHEDIR = os.path.expanduser("~/.bazaar/devtemp")
CACHEDIR = None 

def cached_make(maker, *args):
    if CACHEDIR is None:
        return maker(*args)
    olddir = os.getcwd()
    try:
        if not os.path.exists(CACHEDIR):
            os.makedirs(CACHEDIR)
        os.chdir(CACHEDIR)
        cache_name = "_".join([maker.__name__] + [str(x) for x in args])
        if not os.path.exists(cache_name):
            os.mkdir(cache_name)
            os.chdir(cache_name)
            try:
                maker(*args)
            except:
                os.chdir(CACHEDIR)
                shutil.rmtree(cache_name)
                raise
            os.chdir(CACHEDIR)
                
        for subdir in os.listdir(cache_name):
            shutil.copytree(os.path.join(cache_name, subdir),
                            os.path.join(olddir, subdir))
    finally:
        os.chdir(olddir)

class BundleBenchmark(Benchmark):
    """
    The bundle tests should (also) be done at a lower level with
    direct call to the bzrlib."""
   
    def make_kernel_like_tree_committed(self): 
        cached_make(self.make_kernel_like_tree)
        self.run_bzr('add')
        self.run_bzr('commit', '-m', 'initial import')

    def test_create_bundle_known_kernel_like_tree(self):
        """
        Create a bundle for a kernel sized tree with no ignored, unknowns,
        or added and one commit.""" 
        cached_make(self.make_kernel_like_tree_committed)
        self.time(self.run_bzr, 'bundle', '--revision', '..-1')

    def test_create_bundle_many_commit_tree (self):
        """
        Create a bundle for a tree with many commits but no changes.""" 
        cached_make(self.make_many_commit_tree)
        self.time(self.run_bzr, 'bundle', '--revision', '..-1')

    def test_create_bundle_heavily_merged_tree(self):
        """
        Create a bundle for a heavily merged tree.""" 
        cached_make(self.make_heavily_merged_tree)
        self.time(self.run_bzr, 'bundle', '--revision', '..-1')
        
    def test_apply_bundle_known_kernel_like_tree(self):
        """
        Create a bundle for a kernel sized tree with no ignored, unknowns,
        or added and one commit.""" 
        cached_make(self.make_kernel_like_tree_committed)
        f = file('../bundle', 'wb')
        try:
            f.write(self.run_bzr('bundle', '--revision', '..-1')[0])
        finally:
            f.close()
        self.run_bzr("init", "../branch_a")
        os.chdir('../branch_a')
        self.time(self.run_bzr, 'merge', '../bundle')

 
class BundleLibraryLevelBenchmark(Benchmark):

    def make_parametrized_tree(self, num_files, num_revisions,
                               num_files_in_bundle):
        """Create a tree with given parameters. Always creates 2 levels of
        directories with the given number of files. Then the given number of
        revisions are created, changing some lines in one files in each
        revision. Only num_files_in_bundle files are changed in these
        revisions.

        :param num_files: number of files in tree
        :param num_revisions: number of revisions
        :param num_files_in_bundle: number of files changed in the revisions
        """
        directories = []
        files = []
        count = 0
        for outer in range(num_files // 64 + 1):
            directories.append("%s/" % outer)
            for middle in range(8):
                prefix = "%s/%s/" % (outer, middle)
                directories.append(prefix)
                for filename in range(min(8, num_files - count)):
                    count += 1
                    files.append(prefix + str(filename))
        self.run_bzr('init')
        self.build_tree(directories + files)
        for d in directories:
            self.run_bzr('add', d)
        self.run_bzr('commit', '-m', 'initial repo layout')
        # create revisions
        affected_files = files[:num_files_in_bundle]
        count = 0
        for changes_file in range(num_revisions // num_files_in_bundle + 1):
            for f in affected_files:
                count += 1
                if count >= num_revisions:
                    break
                content = "\n".join([str(i) for i in range(changes_file)] +
                                    [str(changes_file)] * 5) + "\n"
                self.build_tree_contents([(f, content)])
                self.run_bzr("commit", '-m', 'some changes')
        assert count >= num_revisions

    def _time_read_write(self):
        branch, _ = Branch.open_containing(".")
        revision_history = branch.revision_history()
        bundle_text = StringIO()
        self.time(write_bundle, branch.repository, revision_history[-1],
                  None, bundle_text)
        bundle_text.seek(0)
        self.time(read_bundle, bundle_text)

    def test_few_files_small_tree_1_revision(self):
        cached_make(self.make_parametrized_tree, 5, 1, 5)
        self._time_read_write()

    def test_few_files_small_tree_500_revision(self):
        cached_make(self.make_parametrized_tree, 5, 500, 5)
        self._time_read_write()

    def test_few_files_small_tree_1000_revision(self):
        cached_make(self.make_parametrized_tree, 5, 1000, 5)
        self._time_read_write()

    def test_few_files_moderate_tree_1_revision(self):
        cached_make(self.make_parametrized_tree, 100, 1, 5)
        self._time_read_write()

    def test_few_files_moderate_tree_500_revision(self):
        cached_make(self.make_parametrized_tree, 100, 500, 5)
        self._time_read_write()

    def test_few_files_moderate_tree_1000_revision(self):
        cached_make(self.make_parametrized_tree, 100, 1000, 5)
        self._time_read_write()

    def test_some_files_moderate_tree_1_revision(self):
        cached_make(self.make_parametrized_tree, 100, 1, 100)
        self._time_read_write()

    def test_some_files_moderate_tree_500_revision(self):
        cached_make(self.make_parametrized_tree, 100, 500, 100)
        self._time_read_write()

    def test_some_files_moderate_tree_1000_revision(self):
        cached_make(self.make_parametrized_tree, 100, 1000, 100)
        self._time_read_write()

    def test_few_files_big_tree_1_revision(self):
        cached_make(self.make_parametrized_tree, 1000, 1, 5)
        self._time_read_write()

    def test_few_files_big_tree_500_revision(self):
        cached_make(self.make_parametrized_tree, 1000, 500, 5)
        self._time_read_write()

    def test_few_files_big_tree_1000_revision(self):
        cached_make(self.make_parametrized_tree, 1000, 1000, 5)
        self._time_read_write()

    def test_some_files_big_tree_1_revision(self):
        cached_make(self.make_parametrized_tree, 1000, 1, 100)
        self._time_read_write()

    def test_some_files_big_tree_500_revision(self):
        cached_make(self.make_parametrized_tree, 1000, 500, 100)
        self._time_read_write()

    def test_some_files_big_tree_1000_revision(self):
        cached_make(self.make_parametrized_tree, 1000, 1000, 100)
        self._time_read_write()

    def test_many_files_big_tree_1_revision(self):
        cached_make(self.make_parametrized_tree, 1000, 1, 1000)
        self._time_read_write()

    def test_many_files_big_tree_500_revision(self):
        cached_make(self.make_parametrized_tree, 1000, 500, 1000)
        self._time_read_write()

    def test_many_files_big_tree_1000_revision(self):
        cached_make(self.make_parametrized_tree, 1000, 1000, 1000)
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
        cached_make(self.make_parametrized_tree, %s, %s, %s)
        self._time_read_write()
""" % (bundlefiles_h, treesize_h, num_revisions,
       treesize, num_revisions, bundlefiles)
                print code 

