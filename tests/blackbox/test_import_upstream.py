#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#    Copyright (C) 2010 Canonical Ltd
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

"""Tests for import-upstream."""

from debian.changelog import Version

from .test_import_dsc import TestBaseImportDsc
from ..test_import_dsc import PristineTarFeature


class TestImportUpstream(TestBaseImportDsc):

    def setUp(self):
        TestBaseImportDsc.setUp(self)
        self.requireFeature(PristineTarFeature)

    def assertHasImportArtifacts(self, tree, upstream_version=None):
        if upstream_version is None:
            upstream_version = self.upstream_version
        upstream_tag = self.upstream_tag(upstream_version)
        tags = tree.branch.tags
        # If it imported, we have a tag
        imported_rev = tags.lookup_tag(upstream_tag)
        # For a working revision tree
        revtree = tree.branch.repository.revision_tree(imported_rev)
        revtree.lock_read()
        self.addCleanup(revtree.unlock)
        return revtree

    def assertUpstreamContentAndFileIdFromTree(self, revtree, fromtree):
        """Check what content and file ids revtree has."""
        # that does not have debian/
        self.assertEqual(None, revtree.path2id('debian'))
        # and does have the same fileid for README as in tree
        self.assertNotEqual(None, revtree.path2id('README'))
        self.assertEqual(fromtree.path2id('README'), revtree.path2id('README'))

    def make_upstream_tree(self):
        """Make an upstream tree with its own history."""
        upstreamtree = self.make_branch_and_tree('upstream')
        self.make_unpacked_upstream_source(transport=upstreamtree.controldir.root_transport)
        upstreamtree.smart_add(['upstream'])
        upstreamtree.commit('upstream release')
        return upstreamtree

    def make_upstream_change(self, upstreamtree):
        """Commit a change to upstreamtree."""
        # Currently an empty commit, but we may need file content changes to be
        # thorough?
        return upstreamtree.commit('new commit')

    def make_workingdir(self):
        """Make a working directory with both upstream source and debian packaging."""
        tree = self.make_branch_and_tree('working')
        self.make_unpacked_upstream_source(transport=tree.controldir.root_transport)
        self.make_debian_dir(tree.controldir.root_transport.local_abspath('debian'))
        tree.smart_add(['working'])
        tree.commit('save changes')
        return tree

    def upstream_tag(self, version):
        return "upstream-%s" % version

    def test_import_upstream_no_branch_no_prior_tarball(self):
        self.make_upstream_tarball()
        self.make_real_source_package()
        tree = self.make_branch_and_tree('working')
        self.make_unpacked_upstream_source(transport=tree.controldir.root_transport)
        self.make_debian_dir(tree.controldir.root_transport.local_abspath('debian'))
        tree.smart_add(['working'])
        tree.commit('save changes')
        tar_path = "../%s" % self.upstream_tarball_name
        out, err = self.run_bzr(['import-upstream', self.upstream_version,
            tar_path], working_dir='working')
        self.assertEqual('Imported %s as tag:upstream-%s.\n' % (tar_path,
            self.upstream_version), out)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertFalse(tree.has_changes())
        revtree = self.assertHasImportArtifacts(tree)
        self.assertUpstreamContentAndFileIdFromTree(revtree, tree)

    def test_import_upstream_with_branch_no_prior_tarball(self):
        self.make_upstream_tarball()
        # The two branches are deliberately disconnected, to reflect likely
        # situations where this is first called.
        upstreamtree = self.make_upstream_tree()
        tree = self.make_workingdir()
        self.run_bzr(['import-upstream', self.upstream_version, "../%s" %
            self.upstream_tarball_name, '../upstream'],
            working_dir='working')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertFalse(tree.has_changes())
        revtree = self.assertHasImportArtifacts(tree)
        self.assertUpstreamContentAndFileIdFromTree(revtree, upstreamtree)

    def test_import_upstream_with_branch_prior_tarball(self):
        self.make_upstream_tarball()
        upstreamtree = self.make_upstream_tree()
        tree = self.make_workingdir()
        # XXX: refactor: make this an API call - running blackbox in test prep
        # is ugly.
        self.run_bzr(['import-upstream', self.upstream_version, "../%s" %
            self.upstream_tarball_name, '../upstream'],
            working_dir='working')
        new_version = Version('0.2-1')
        self.make_upstream_tarball(new_version.upstream_version)
        upstream_parent = self.make_upstream_change(upstreamtree)
        self.run_bzr(['import-upstream', new_version.upstream_version, "../%s" %
            self._upstream_tarball_name(self.package_name, new_version.upstream_version), '../upstream'],
            working_dir='working')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertFalse(tree.has_changes())
        revtree = self.assertHasImportArtifacts(tree, new_version.upstream_version)
        self.assertUpstreamContentAndFileIdFromTree(revtree, upstreamtree)
        # Check parents: we want
        # [previous_import, upstream_parent] to reflect that the 'branch' is
        # the tarball branch aka upstream branch [ugh], and then a merge in
        # from upstream so that cherrypicks do the right thing.
        tags = tree.branch.tags
        self.assertEqual([tags.lookup_tag(self.upstream_tag(self.upstream_version)),
            upstreamtree.branch.last_revision()],
            revtree.get_parent_ids())


# vim: ts=4 sts=4 sw=4

