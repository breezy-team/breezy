#    test_merge_upstream.py -- Testsuite for builddeb's upstream merging.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
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
#

import os
import tarfile
import shutil

from debian_bundle.changelog import Changelog, Version

from bzrlib.errors import (BzrCommandError,
                           NoSuchFile,
                           NoSuchTag,
                           TagAlreadyExists,
                           )
from bzrlib.tests import KnownFailure, TestCase, TestCaseWithTransport
from bzrlib.workingtree import WorkingTree

from bzrlib.plugins.builddeb.errors import (
        UpstreamAlreadyImported,
        )
from bzrlib.plugins.builddeb.import_dsc import (
        DistributionBranch,
        DistributionBranchSet,
        )
from bzrlib.plugins.builddeb.merge_upstream import (
        merge_upstream, 
        upstream_branch_version,
        upstream_tag_to_version
        )


def write_to_file(filename, contents):
  """Indisciminately write the contents to the filename specified."""

  f = open(filename, 'wb')
  try:
    f.write(contents)
  finally:
    f.close()


class TestMergeUpstreamNormal(TestCaseWithTransport):
  """Test that builddeb can merge upstream in normal mode"""

  upstream_rev_id_1 = 'upstream-1'
  upstream_tarball = '../package-0.2.tar.gz'

  def build_tarball(self):
    tar = tarfile.open(self.upstream_tarball, 'w:gz')
    try:
      tar.add('package-0.2')
    finally:
      tar.close()
    shutil.rmtree('package-0.2')

  def make_new_upstream(self):
    self.build_tree(['package-0.2/', 'package-0.2/README-NEW',
                     'package-0.2/CHANGELOG'])
    write_to_file('package-0.2/CHANGELOG', 'version 2\n')
    self.build_tarball()

  def make_first_upstream_commit(self):
    self.wt = self.make_branch_and_tree('.')
    self.build_tree(['README', 'CHANGELOG'])
    self.wt.add(['README', 'CHANGELOG'], ['README-id', 'CHANGELOG-id'])
    self.wt.commit('upstream version 1', rev_id=self.upstream_rev_id_1)

  def make_first_debian_commit(self):
    self.build_tree(['debian/'])
    cl = Changelog()
    cl.new_block(package='package',
                 version=Version('0.1-1'),
                 distributions='unstable',
                 urgency='low',
                 author='James Westby <jw+debian@jameswestby.net>',
                 date='Thu,  3 Aug 2006 19:16:22 +0100',
                 )
    cl.add_change('');
    cl.add_change('  * Initial packaging.');
    cl.add_change('');
    f = open('debian/changelog', 'wb')
    try:
      cl.write_to_open_file(f)
    finally:
      f.close()
    self.wt.add(['debian/', 'debian/changelog'],
                ['debian-id', 'debian-changelog-id'])
    self.wt.commit('debian version 1-1', rev_id='debian-1-1')

  def make_new_upstream_with_debian(self):
    self.build_tree(['package-0.2/', 'package-0.2/README-NEW',
                     'package-0.2/CHANGELOG', 'package-0.2/debian/',
                     'package-0.2/debian/changelog'])
    write_to_file('package-0.2/CHANGELOG', 'version 2\n')
    self.build_tarball()

  def make_distribution_branch(self):
    db = DistributionBranch("debian", self.wt.branch, None,
            tree=self.wt)
    dbs = DistributionBranchSet()
    dbs.add_branch(db)
    return db

  def perform_upstream_merge(self):
    """Perform a simple upstream merge.

    :returns: the working tree after the merge.
    :rtype: WorkingTree
    """
    self.make_first_upstream_commit()
    self.wt.branch.tags.set_tag('upstream-debian-0.1',
            self.wt.branch.last_revision())
    self.make_first_debian_commit()
    self.make_new_upstream()
    db = self.make_distribution_branch()
    db.merge_upstream(self.upstream_tarball, Version('0.2-1'),
            Version('0.1-1'))
    return self.wt

  def check_changes(self, changes, added=[], removed=[], modified=[],
                      renamed=[]):
        def check_one_type(type, expected, actual):
            def make_set(list):
                output = set()
                for item in list:
                    if item[2] == 'directory':
                        output.add(item[0] + '/')
                    else:
                        output.add(item[0])
                return output
            exp = set(expected)
            real = make_set(actual)
            missing = exp.difference(real)
            extra = real.difference(exp)
            if len(missing) > 0:
                self.fail("Some expected paths not found %s in the changes: "
                          "%s, expected %s, got %s." % (type, str(missing),
                              str(expected), str(actual)))
            if len(extra) > 0:
                self.fail("Some extra paths found %s in the changes: "
                          "%s, expected %s, got %s." % (type, str(extra),
                              str(expected), str(actual)))
        check_one_type("added", added, changes.added)
        check_one_type("removed", removed, changes.removed)
        check_one_type("modified", modified, changes.modified)
        check_one_type("renamed", renamed, changes.renamed)

  def check_simple_merge_results(self):
    wt = self.wt
    self.check_changes(wt.changes_from(wt.basis_tree()),
            added=["README-NEW"], modified=["CHANGELOG"],
            removed=["README"])
    parents = wt.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(wt.conflicts(), [])
    rh = wt.branch.revision_history()
    self.assertEqual(wt.branch.tags.lookup_tag('upstream-debian-0.2'),
            parents[1])

  def test_merge_upstream(self):
    self.perform_upstream_merge()
    self.check_simple_merge_results()

  def test_merge_upstream_handles_no_source(self):
    self.make_first_upstream_commit()
    self.wt.branch.tags.set_tag('upstream-debian-0.1',
            self.wt.branch.last_revision())
    self.make_first_debian_commit()
    db = self.make_distribution_branch()
    try:
        self.assertRaises(NoSuchFile, db.merge_upstream,
                'source', Version('0.2-1'), Version('0.1-1'))
    except IOError:
        raise KnownFailure("Transport not used to retrieve tarball.")

  def test_merge_upstream_new_tag_extant(self):
    self.make_first_upstream_commit()
    self.wt.branch.tags.set_tag('upstream-debian-0.1',
            self.wt.branch.last_revision())
    self.make_first_debian_commit()
    self.make_new_upstream()
    self.wt.branch.tags.set_tag('upstream-debian-0.2',
            self.wt.branch.last_revision())
    db = self.make_distribution_branch()
    self.assertRaises(UpstreamAlreadyImported, db.merge_upstream,
                      self.upstream_tarball, Version('0.2-1'),
                      Version('0.1-1'))

  def perform_conflicted_merge(self):
    self.make_first_upstream_commit()
    self.wt.branch.tags.set_tag('upstream-debian-0.1',
            self.wt.branch.last_revision())
    write_to_file('CHANGELOG', 'debian version\n')
    self.make_first_debian_commit()
    self.make_new_upstream_with_debian()
    db = self.make_distribution_branch()
    db.merge_upstream(self.upstream_tarball, Version('0.2-1'),
            Version('0.1-1'))
    return self.wt

  def test_merge_upstream_gives_correct_tree_on_conficts(self):
    """Check that a merge leaves the tree as expected with conflicts."""
    wt = self.perform_conflicted_merge()
    self.failUnlessExists('CHANGELOG')
    self.failUnlessExists('README-NEW')
    self.failIfExists('README')
    f = open('CHANGELOG')
    try:
      self.assertEqual(f.read(), "<<<<<<< TREE\ndebian version\n=======\n"
                       "version 2\n>>>>>>> MERGE-SOURCE\n")
    finally:
      f.close()
    self.failUnlessExists('debian/changelog')
    self.failIfExists('debian.moved/changelog')

  def test_merge_upstream_gives_correct_status(self):
    wt = self.perform_conflicted_merge()
    basis = wt.basis_tree()
    changes = wt.changes_from(basis, want_unchanged=True,
                              want_unversioned=True)
    self.check_changes(wt.changes_from(wt.basis_tree()),
            added=["README-NEW"],
            modified=["CHANGELOG", "debian/changelog"],
            removed=["README"])

  def test_merge_upstream_gives_correct_parents(self):
    wt = self.perform_conflicted_merge()
    parents = wt.get_parent_ids()
    self.assertEqual(len(parents), 2)

  def test_merge_upstream_gives_correct_conflicts(self):
    wt = self.perform_conflicted_merge()
    conflicts = wt.conflicts()
    self.assertEqual(len(conflicts), 2)
    self.assertEqual(conflicts[0].path, 'CHANGELOG')
    self.assertEqual(conflicts[0].file_id, 'CHANGELOG-id')
    self.assertEqual(conflicts[0].typestring, 'text conflict')
    self.assertEqual(conflicts[1].path, 'debian/changelog')
    self.assertEqual(conflicts[1].typestring, 'text conflict')

  def test_merge_upstream_gives_correct_history(self):
    wt = self.perform_conflicted_merge()
    rh = wt.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.assertEqual(rh[0], 'upstream-1')

  def test_merge_upstream_tags_new_version(self):
    wt = self.perform_conflicted_merge()
    rh = wt.branch.revision_history()
    self.assertEqual(wt.branch.tags.lookup_tag('upstream-debian-0.2'),
            wt.get_parent_ids()[1])


class TestUpstreamBranchVersion(TestCase):
  """Test that the upstream version of a branch can be determined correctly.
  """

  def test_snapshot_none_existing(self):
    self.assertEquals(Version("1.2+bzr1"),
        upstream_branch_version(["somerevid"], {}, "bla", "1.2"))

  def test_new_tagged_release(self):
    """Last revision is tagged - use as upstream version."""
    self.assertEquals(Version("1.3"), 
        upstream_branch_version(["somerevid"], {"somerevid": ["1.3"]}, "bla", "1.2"))

  def test_refresh_snapshot_pre(self):
    self.assertEquals(Version("1.3~bzr2"), 
        upstream_branch_version(["oldrevid", "somerevid"], {}, "bla", "1.3~bzr1"))

  def test_refresh_snapshot_post(self):
    self.assertEquals(Version("1.3+bzr2"), 
        upstream_branch_version(["oldrevid", "somerevid"], {}, "bla", "1.3+bzr1"))

  def test_new_tag_refresh_snapshot(self):
    self.assertEquals(Version("1.3+bzr3"), 
        upstream_branch_version(["oldrevid", "somerevid", "newrevid"], 
                                {"somerevid": ["1.3"]}, "bla", "1.2+bzr1"))


class TestUpstreamTagToVersion(TestCase):

  def test_prefix(self):
    self.assertEquals(Version("5.0"), upstream_tag_to_version("upstream-5.0"))

  def test_gibberish(self):
    self.assertIs(None, upstream_tag_to_version("blabla"))

  def test_vprefix(self):
    self.assertEquals(Version("2.0"), upstream_tag_to_version("v2.0"))

  def test_plain(self):
    self.assertEquals(Version("2.0"), upstream_tag_to_version("2.0"))

  def test_package_prefix(self):
    self.assertEquals(Version("42.0"), upstream_tag_to_version("bla-42.0", "bla"))


# vim: ts=2 sts=2 sw=2

