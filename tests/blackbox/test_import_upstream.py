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

import os
import shutil
import subprocess
import tarfile

from bzrlib import tests

from bzrlib.plugins.builddeb.tests.blackbox.test_import_dsc import TestBaseImportDsc
from bzrlib.plugins.builddeb.tests.test_import_dsc import PristineTarFeature


class TestImportUpstream(TestBaseImportDsc):

    def assertHasImportArtifacts(self, tree):
        upstream_tag = 'upstream-%s' % self.upstream_version
        tags = tree.branch._format.make_tags(tree.branch)
        # If it imported, we have a tag
        imported_rev = tags.lookup_tag(upstream_tag)
        # For a working revision tree
        revtree = tree.branch.repository.revision_tree(imported_rev)
        revtree.lock_read()
        self.addCleanup(revtree.unlock)
        return revtree

    def test_import_upstream_no_branch_no_prior_tarball(self):
        self.requireFeature(PristineTarFeature)
        self.make_upstream_tarball()
        self.make_real_source_package()
        tree = self.make_branch_and_tree('working')
        self.make_unpacked_upstream_source(transport=tree.bzrdir.root_transport)
        self.make_debian_dir(tree.bzrdir.root_transport.local_abspath('debian'))
        tree.smart_add(['working'])
        tree.commit('save changes')
        self.run_bzr(['import-upstream', self.upstream_version,
            os.path.abspath(self.upstream_tarball_name)], working_dir='working')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertFalse(tree.has_changes())
        revtree = self.assertHasImportArtifacts(tree)
        # that does not have debian/
        self.assertEqual(None, revtree.path2id('debian'))
        # and does have the same fileid for README
        self.assertNotEqual(None, revtree.path2id('README'))
        self.assertEqual(tree.path2id('README'), revtree.path2id('README'))

    def test_import_upstream_with_branch_no_prior_tarball(self):
        self.requireFeature(PristineTarFeature)
        self.make_upstream_tarball()
        # The two branches are deliberately disconnected, to reflect likely
        # situations where this is first called.
        upstreamtree = self.make_branch_and_tree('upstream')
        self.make_unpacked_upstream_source(transport=upstreamtree.bzrdir.root_transport)
        upstreamtree.smart_add(['upstream'])
        upstreamtree.commit('upstream release')
        tree = self.make_branch_and_tree('working')
        self.make_unpacked_upstream_source(transport=tree.bzrdir.root_transport)
        self.make_debian_dir(tree.bzrdir.root_transport.local_abspath('debian'))
        tree.smart_add(['working'])
        tree.commit('save changes')
        self.run_bzr(['import-upstream', self.upstream_version,
            os.path.abspath(self.upstream_tarball_name), '../upstream'],
            working_dir='working')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertFalse(tree.has_changes())
        revtree = self.assertHasImportArtifacts(tree)
        # that does not have debian/
        self.assertEqual(None, revtree.path2id('debian'))
        # and has the fileid from upstream for README.
        self.assertNotEqual(None, revtree.path2id('README'))
        self.assertEqual(upstreamtree.path2id('README'), revtree.path2id('README'))

# vim: ts=4 sts=4 sw=4

