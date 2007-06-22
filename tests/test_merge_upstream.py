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
import shutil
import tarfile

from bzrlib.errors import BzrCommandError
from bzrlib.revisionspec import RevisionSpec
from bzrlib.tests import TestCaseWithTransport

from merge_upstream import merge_upstream


def write_to_file(filename, contents):
  """Indisciminately write the contents to the filename specified."""

  f = open(filename, 'wb')
  try:
    f.write(contents)
  finally:
    f.close()

def make_revspec(rev_id):
  """Turn the rev_id passed in to a revision spec."""
  return RevisionSpec.from_string('revid:' + rev_id)

class TestSimpleMergeUpstreamNormal(TestCaseWithTransport):
  """Test that builddeb can merge upstream in normal mode"""

  upstream_rev_id_1 = 'upstream-1'
  upstream_tarball = '../package-0.2.tar.gz'

  def make_first_upstream_commit(self):
    self.wt = self.make_branch_and_tree('.')
    self.build_tree(['README', 'CHANGELOG'])
    self.wt.add(['README', 'CHANGELOG'], ['README-id', 'CHANGELOG-id'])
    self.wt.commit('upstream version 1', rev_id=self.upstream_rev_id_1)

  def make_first_debian_commit(self):
    self.build_tree(['debian/', 'debian/changelog'])
    self.wt.add(['debian/', 'debian/changelog'],
                ['debian-id', 'debian-changelog-id'])
    self.wt.commit('debian version 1-1', rev_id='debian-1-1')

  def make_new_upstream_tarball(self):
    self.build_tree(['package-0.2/', 'package-0.2/README-NEW',
                     'package-0.2/CHANGELOG'])
    write_to_file('package-0.2/CHANGELOG', 'version 2\n')
    tar = tarfile.open(self.upstream_tarball, 'w:gz')
    try:
      tar.add('package-0.2')
    finally:
      tar.close()
    shutil.rmtree('package-0.2')

  def perform_upstream_merge(self):
    """Perform a simple upstream merge.

    :returns: the working tree after the merge.
    :rtype: WorkingTree
    """
    self.make_first_upstream_commit()
    old_upstream_revision = self.wt.branch.last_revision()
    self.make_first_debian_commit()
    self.make_new_upstream_tarball()
    merge_upstream(self.wt, self.upstream_tarball,
                   make_revspec(old_upstream_revision))
    os.unlink(self.upstream_tarball)
    return self.wt

  def test_merge_upstream_gives_correct_tree(self):
    """Check that a merge leaves the tree as expected."""
    wt = self.perform_upstream_merge()
    self.failUnlessExists('CHANGELOG')
    self.failUnlessExists('README-NEW')
    self.failIfExists('README')
    self.failUnlessExists('debian/changelog')
    f = open('CHANGELOG')
    try:
      self.assertEqual(f.read(), 'version 2\n')
    finally:
      f.close()

  def test_merge_upstream_gives_correct_status(self):
    wt = self.perform_upstream_merge()
    basis = wt.basis_tree()
    changes = wt.changes_from(basis, want_unchanged=True,
                              want_unversioned=True)
    added = [('debian', 'debian-id', 'directory'),
             ('debian/changelog', 'debian-changelog-id', 'file')]
    self.assertEqual(changes.added, added)
    self.assertEqual(changes.removed, [])
    self.assertEqual(changes.renamed, [])
    self.assertEqual(changes.modified, [])
    self.assertEqual(changes.unchanged[0],
                     ('CHANGELOG', 'CHANGELOG-id', 'file'))
    self.assertEqual(changes.unchanged[1][0], 'README-NEW')
    self.assertEqual(changes.unchanged[1][2], 'file')
    self.assertEqual(changes.unversioned, [])
    self.assertEqual(changes.kind_changed, [])
    parents = wt.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[1], 'debian-1-1')
    self.assertEqual(wt.conflicts(), [])

  def test_merge_upstream_gives_correct_history(self):
    wt = self.perform_upstream_merge()
    rh = wt.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.assertEqual(rh[0], self.upstream_rev_id_1)
    self.assertEqual(wt.branch.repository.get_revision(rh[1]).message,
                     'import upstream from package-0.2.tar.gz')

  def test_merge_upstream_requires_clean_tree(self):
    wt = self.make_branch_and_tree('.')
    self.build_tree(['file'])
    wt.add(['file'])
    self.assertRaises(BzrCommandError, merge_upstream, wt, 'source', 1)

  def test_merge_upstream_handles_no_source(self):
    self.make_first_upstream_commit()
    old_upstream_revision = self.wt.branch.last_revision()
    self.make_first_debian_commit()
    self.assertRaises(BzrCommandError, merge_upstream, self.wt, 'source',
                      make_revspec(old_upstream_revision))

class TestConflictMergeUpstreamNormal(TestCaseWithTransport):
  """Test merge upstream with conflicts in the new version."""

  def perform_upstream_merge(self):
    """Perform an upstream merge that causes conflicts.

    :returns: the working tree after the merge.
    :rtype: WorkingTree
    """
    wt = self.make_branch_and_tree('.')
    # create the original upstream import
    self.build_tree(['README', 'CHANGELOG'])
    wt.add(['README', 'CHANGELOG'], ['README-id', 'CHANGELOG-id'])
    wt.commit('upstream version 1', rev_id='upstream-1')
    old_upstream_revision = wt.branch.last_revision()
    # create the debian branch on top
    self.build_tree(['debian/', 'debian/changelog'])
    wt.add(['debian/', 'debian/changelog'],
           ['debian-id', 'debian-changelog-id'])
    write_to_file('CHANGELOG', 'debian version\n')
    wt.commit('debian version 1-1', rev_id='debian-1-1')
    # create the new upstream release to import
    self.build_tree(['package-0.2/', 'package-0.2/README-NEW',
                     'package-0.2/CHANGELOG', 'package-0.2/debian/',
                     'package-0.2/debian/changelog'])
    write_to_file('package-0.2/CHANGELOG', 'version 2\n')
    tar = tarfile.open('package-0.2.tar.gz', 'w:gz')
    try:
      tar.add('package-0.2')
    finally:
      tar.close()
    shutil.rmtree('package-0.2')
    merge_upstream(wt, 'package-0.2.tar.gz',
                   make_revspec(old_upstream_revision))
    os.unlink('package-0.2.tar.gz')
    return wt

  def test_merge_upstream_gives_correct_tree(self):
    """Check that a merge leaves the tree as expected."""
    wt = self.perform_upstream_merge()
    self.failUnlessExists('CHANGELOG')
    self.failUnlessExists('README-NEW')
    self.failIfExists('README')
    self.failUnlessExists('debian/changelog')
    self.failUnlessExists('debian.moved/changelog')
    f = open('CHANGELOG')
    try:
      self.assertEqual(f.read(), "<<<<<<< TREE\nversion 2\n=======\n"
                       "debian version\n>>>>>>> MERGE-SOURCE\n")
    finally:
      f.close()

  def test_merge_upstream_gives_correct_status(self):
    wt = self.perform_upstream_merge()
    basis = wt.basis_tree()
    changes = wt.changes_from(basis, want_unchanged=True,
                              want_unversioned=True)
    added = [('debian', 'debian-id', 'directory'),
             ('debian/changelog', 'debian-changelog-id', 'file')]
    self.assertEqual(changes.added, added)
    self.assertEqual(changes.removed, [])
    self.assertEqual(len(changes.renamed), 1)
    renamed = changes.renamed[0]
    self.assertEqual(renamed[0], 'debian')
    self.assertEqual(renamed[1], 'debian.moved')
    self.assertEqual(renamed[3], 'directory')
    self.assertEqual(renamed[4], False)
    self.assertEqual(renamed[5], False)
    self.assertEqual(changes.modified,
                     [('CHANGELOG', 'CHANGELOG-id', 'file', True, False)])
    self.assertEqual(changes.kind_changed, [])
    self.assertEqual(len(changes.unchanged), 2)
    self.assertEqual(changes.unchanged[0][0], 'README-NEW')
    self.assertEqual(changes.unchanged[0][2], 'file')
    self.assertEqual(changes.unchanged[1][0], 'debian.moved/changelog')
    self.assertEqual(changes.unchanged[1][2], 'file')
    self.assertEqual(changes.unversioned,
                     [('CHANGELOG.BASE', None, 'file'),
                      ('CHANGELOG.OTHER', None, 'file'),
                      ('CHANGELOG.THIS', None, 'file')])

  def test_merge_upstream_gives_correct_parents(self):
    wt = self.perform_upstream_merge()
    parents = wt.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[1], 'debian-1-1')

  def test_merge_upstream_gives_correct_conflicts(self):
    wt = self.perform_upstream_merge()
    conflicts = wt.conflicts()
    self.assertEqual(len(conflicts), 2)
    self.assertEqual(conflicts[0].path, 'CHANGELOG')
    self.assertEqual(conflicts[0].file_id, 'CHANGELOG-id')
    self.assertEqual(conflicts[0].typestring, 'text conflict')
    self.assertEqual(conflicts[1].action, 'Moved existing file to')
    self.assertEqual(conflicts[1].conflict_path, 'debian')
    self.assertEqual(conflicts[1].conflict_file_id, 'debian-id')
    self.assertEqual(conflicts[1].typestring, 'duplicate')

  def test_merge_upstream_gives_correct_history(self):
    wt = self.perform_upstream_merge()
    rh = wt.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.assertEqual(rh[0], 'upstream-1')
    self.assertEqual(wt.branch.repository.get_revision(rh[1]).message,
                     'import upstream from package-0.2.tar.gz')


