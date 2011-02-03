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

try:
    from debian.changelog import Version
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle.changelog import Version

from bzrlib import tests
from bzrlib.revision import Revision
from bzrlib.tests import TestCase, TestCaseWithTransport

from bzrlib.plugins.builddeb.merge_upstream import (
        upstream_merge_changelog_line,
        package_version,
        _upstream_branch_version,
        upstream_tag_to_version,
        upstream_version_add_revision
        )

# Unless bug #712474 is fixed and available in the minimum bzrlib required, we
# can't use:
# svn_plugin = tests.ModuleAvailableFeature('bzrlib.plugins.svn')
class SvnPluginAvailable(tests.Feature):

    def feature_name(self):
        return 'bzr-svn plugin'

    def _probe(self):
        try:
            import bzrlib.plugins.svn
            return True
        except ImportError:
            return False
svn_plugin = SvnPluginAvailable()


class TestUpstreamVersionAddRevision(TestCaseWithTransport):
  """Test that updating the version string works."""

  def setUp(self):
    super(TestUpstreamVersionAddRevision, self).setUp()
    self.revnos = {}
    self.svn_revnos = {"somesvnrev": 45}
    self.revnos = {"somerev": 42, "somesvnrev": 12}
    self.repository = self

  def revision_id_to_revno(self, revid):
    return self.revnos[revid]

  def get_revision(self, revid):
    rev = Revision(revid)
    if revid in self.svn_revnos:
      self.requireFeature(svn_plugin)
      # Fake a bzr-svn revision
      rev.foreign_revid = ("uuid", "bp", self.svn_revnos[revid])
      from bzrlib.plugins.svn import mapping
      rev.mapping = mapping.mapping_registry.get_default()()
    return rev

  def test_update_plus_rev(self):
    self.assertEquals("1.3+bzr42", 
        upstream_version_add_revision(self, "1.3+bzr23", "somerev"))

  def test_update_tilde_rev(self):
    self.assertEquals("1.3~bzr42", 
        upstream_version_add_revision(self, "1.3~bzr23", "somerev"))

  def test_new_rev(self):
    self.assertEquals("1.3+bzr42", 
        upstream_version_add_revision(self, "1.3", "somerev"))

  def test_svn_new_rev(self):
    
    self.assertEquals("1.3+svn45", 
        upstream_version_add_revision(self, "1.3", "somesvnrev"))

  def test_svn_plus_rev(self):
    self.assertEquals("1.3+svn45", 
        upstream_version_add_revision(self, "1.3+svn3", "somesvnrev"))

  def test_svn_tilde_rev(self):
    self.assertEquals("1.3~svn45", 
        upstream_version_add_revision(self, "1.3~svn800", "somesvnrev"))


class TestUpstreamBranchVersion(TestCase):
  """Test that the upstream version of a branch can be determined correctly.
  """

  def get_suffix(self, version_string, revid):
    revno = self.revhistory.index(revid)+1
    if "bzr" in version_string:
      return "%sbzr%d" % (version_string.split("bzr")[0], revno)
    return "%s+bzr%d" % (version_string, revno)

  def test_snapshot_none_existing(self):
    self.revhistory = ["somerevid"]
    self.assertEquals(Version("1.2+bzr1"),
        _upstream_branch_version(self.revhistory, {}, "bla", "1.2", self.get_suffix))

  def test_snapshot_nothing_new(self):
    self.revhistory = []
    self.assertEquals(Version("1.2"),
        _upstream_branch_version(self.revhistory, {}, "bla", "1.2", self.get_suffix))

  def test_new_tagged_release(self):
    """Last revision is tagged - use as upstream version."""
    self.revhistory = ["somerevid"]
    self.assertEquals(Version("1.3"), 
        _upstream_branch_version(self.revhistory, {"somerevid": ["1.3"]}, "bla", "1.2", self.get_suffix))

  def test_refresh_snapshot_pre(self):
    self.revhistory = ["oldrevid", "somerevid"]
    self.assertEquals(Version("1.3~bzr2"), 
        _upstream_branch_version(self.revhistory, {}, "bla", "1.3~bzr1", self.get_suffix))

  def test_refresh_snapshot_post(self):
    self.revhistory = ["oldrevid", "somerevid"]
    self.assertEquals(Version("1.3+bzr2"), 
        _upstream_branch_version(self.revhistory, {}, "bla", "1.3+bzr1", self.get_suffix))

  def test_new_tag_refresh_snapshot(self):
    self.revhistory = ["oldrevid", "somerevid", "newrevid"]
    self.assertEquals(Version("1.3+bzr3"), 
        _upstream_branch_version(self.revhistory, 
                                {"somerevid": ["1.3"]}, "bla", "1.2+bzr1", self.get_suffix))


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


class TestPackageVersion(TestCase):

  def test_simple_debian(self):
    self.assertEquals(Version("1.2-1"),
        package_version("1.2", "debian"))

  def test_simple_ubuntu(self):
    self.assertEquals(Version("1.2-0ubuntu1"),
        package_version("1.2", "ubuntu"))

  def test_debian_with_dash(self):
    self.assertEquals(Version("1.2-0ubuntu1-1"),
        package_version("1.2-0ubuntu1", "debian"))

  def test_ubuntu_with_dash(self):
    self.assertEquals(Version("1.2-1-0ubuntu1"),
        package_version("1.2-1", "ubuntu"))

  def test_ubuntu_with_epoch(self):
    self.assertEquals(Version("3:1.2-1-0ubuntu1"),
        package_version("1.2-1", "ubuntu", "3"))


class UpstreamMergeChangelogLineTests(TestCase):

    def test_release(self):
        self.assertEquals("New upstream release.", upstream_merge_changelog_line("1.0"))

    def test_bzr_snapshot(self):
        self.assertEquals("New upstream snapshot.",
            upstream_merge_changelog_line("1.0+bzr3"))

    def test_git_snapshot(self):
        self.assertEquals("New upstream snapshot.",
            upstream_merge_changelog_line("1.0~git20101212"))

    def test_plus(self):
        self.assertEquals("New upstream release.",
            upstream_merge_changelog_line("1.0+dfsg1"))
