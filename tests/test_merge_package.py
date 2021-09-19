#!/usr/bin/env python
# -*- coding: iso-8859-15 -*-
#    test_merge_package.py -- Merge packaging branches, fix ancestry as needed.
#    Copyright (C) 2009 Canonical Ltd.
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

import string

from debian.changelog import Version

from .. import merge_package as MP
from ..import_dsc import DistributionBranch

from . import TestCaseWithTransport

_Debian_changelog = '''\
ipsec-tools (%s) unstable; urgency=high

  * debian packaging -- %s

 -- Nico Golde <nion@debian.org>  Tue, %02d May 2009 13:26:14 +0200

'''

_Ubuntu_changelog = '''\
ipsec-tools (%s) karmic; urgency=low

  * ubuntu packaging -- %s

 -- Jamie Strandboge <jamie@ubuntu.com>  Fri, %02d Jul 2009 13:24:17 -0500

'''


def _prepend_log(text, path):
    content = open(path).read()
    with open(path, 'w') as fh:
        fh.write(text+content)


class MergePackageTests(TestCaseWithTransport):

    def test__upstream_version_data(self):
        ubup_o, debp_n, _ubuu, _debu = self._setup_debian_upstream_newer()
        vdata = MP._upstream_version_data(
            debp_n.branch, debp_n.last_revision())
        self.assertEquals(vdata[0], Version('1.10'))

        vdata = MP._upstream_version_data(
            ubup_o.branch, ubup_o.last_revision())
        self.assertEquals(vdata[0], Version('1.2'))

    def test_debian_upstream_newer(self):
        """Diverging upstreams (debian newer) don't cause merge conflicts.

        The debian and ubuntu upstream branches will differ with regard to
        the content of the file 'c'.

        Furthermore the respective packaging branches will have a text
        conflict in 'debian/changelog'.

        The upstream conflict will be resolved by fix_ancestry_as_needed().
        Please note that the debian ancestry is more recent.
        """
        ubup, debp, ubuu, debu = self._setup_debian_upstream_newer()

        # Attempt a plain merge first.
        conflicts = ubup.merge_from_branch(
            debp.branch, to_revision=self.revid_debp_n_C)

        if not isinstance(conflicts, list):
            conflicts = ubup.conflicts()

        # There are two conflicts in the 'c' and the 'debian/changelog' files
        # respectively.
        self.assertEquals(len(conflicts), 2)
        conflict_paths = sorted([c.path for c in conflicts])
        self.assertEquals(conflict_paths, [u'c.moved', u'debian/changelog'])

        # Undo the failed merge.
        ubup.revert()

        # Check the versions present in the tree with the fixed ancestry.
        v3 = "1.2"
        v4 = "1.10"
        db1 = DistributionBranch(ubup.branch, ubup.branch)
        self.assertEqual(
            db1.pristine_upstream_source.has_version("package", v3), True)
        # This version is in the diverged debian upstream tree and will
        # hence not be present in the target ubuntu packaging branch.
        self.assertEqual(
            db1.pristine_upstream_source.has_version("package", v4), False)

        # The ubuntu upstream branch tip.
        ubuu_tip = ubuu.branch.last_revision()
        # The debian upstream branch tip.
        debu_tip = debu.branch.last_revision()
        # The ubuntu packaging branch tip.
        ubup_tip_pre_fix = ubup.branch.last_revision()

        # The first conflict is resolved by calling fix_ancestry_as_needed().
        upstreams_diverged, t_upstream_reverted = MP.fix_ancestry_as_needed(
            ubup, debp.branch)

        # The ancestry did diverge and needed to be fixed.
        self.assertEquals(upstreams_diverged, True)
        # The (temporary) target upstream branch had to be reverted to the
        # source upstream branch since the latter was more recent.
        self.assertEquals(t_upstream_reverted, True)

        # Check the versions present in the tree with the fixed ancestry.
        db2 = DistributionBranch(ubup.branch, ubup.branch)
        self.assertEqual(
            db2.pristine_upstream_source.has_version("package", v3), True)
        # The ancestry has been fixed and the missing debian upstream
        # version should now be present in the target ubuntu packaging
        # branch.
        self.assertEqual(
            db2.pristine_upstream_source.has_version("package", v4), True)

        # Now let's take a look at the fixed ubuntu packaging branch.
        ubup_tip_post_fix = ubup.branch.last_revision()
        ubup_parents_post_fix = ubup.branch.repository.revision_tree(
            ubup_tip_post_fix).get_parent_ids()

        # The tip of the fixed ubuntu packaging branch has 2 parents.
        self.assertEquals(len(ubup_parents_post_fix), 2)

        # The left parent is the packaging branch tip before fixing.
        self.assertEquals(ubup_parents_post_fix[0], ubup_tip_pre_fix)

        # The right parent is derived from a merge
        ubup_parents_sharedupstream = ubup.branch.repository.revision_tree(
            ubup_parents_post_fix[1]).get_parent_ids()
        self.assertEquals(ubup_parents_sharedupstream, [ubuu_tip, debu_tip])

        # Try merging again.
        conflicts = ubup.merge_from_branch(
            debp.branch, to_revision=self.revid_debp_n_C)

        if not isinstance(conflicts, list):
            conflicts = ubup.conflicts()

        # And, voila, only the packaging branch conflict remains.
        conflict_paths = sorted([c.path for c in conflicts])
        self.assertEquals(conflict_paths, [u'debian/changelog'])

    def test_deb_upstream_conflicts_with_ubu_packaging(self):
        """Source upstream conflicts with target packaging -> exception.

        The debian upstream and the ubuntu packaging branches will differ
        with respect to the content of the file 'c'.

        The conflict cannot be resolved by fix_ancestry_as_needed().
        The `SharedUpstreamConflictsWithTargetPackaging` exception is
        thrown instead.
        """
        ubup, debp, ubuu, debu = self._setup_debian_upstream_conflicts()

        self.assertRaises(
            MP.SharedUpstreamConflictsWithTargetPackaging,
            MP.fix_ancestry_as_needed, ubup, debp.branch)

        conflict_paths = sorted([c.path for c in ubup.conflicts()])
        self.assertEquals(conflict_paths, [u'c.moved'])
        # Check that all the merged revisions are now in this repo
        merged_parent = ubup.get_parent_ids()[1]
        its_parents_map = ubup.branch.repository.get_parent_map([
                merged_parent])
        self.assertTrue(merged_parent in its_parents_map)
        its_parents = its_parents_map[merged_parent]
        their_parents = ubup.branch.repository.get_parent_map(its_parents)
        self.assertTrue(its_parents[0] in their_parents)
        self.assertTrue(its_parents[1] in their_parents)

    def test_debian_upstream_older(self):
        """Diverging upstreams (debian older) don't cause merge conflicts.

        The debian and ubuntu upstream branches will differ with regard to
        the content of the file 'c'.

        Furthermore the respective packaging branches will have a text
        conflict in 'debian/changelog'.

        The upstream conflict will be resolved by fix_ancestry_as_needed().
        Please note that the debian ancestry is older in this case.
        """
        ubup, debp, _ubuu, _debu = self._setup_debian_upstream_older()

        # Attempt a plain merge first.
        conflicts = ubup.merge_from_branch(
            debp.branch, to_revision=self.revid_debp_o_C)

        if not isinstance(conflicts, list):
            conflicts = ubup.conflicts()

        # There are two conflicts in the 'c' and the 'debian/changelog' files
        # respectively.
        conflict_paths = sorted([c.path for c in conflicts])
        self.assertEquals(conflict_paths, [u'c.moved', u'debian/changelog'])

        # Undo the failed merge.
        ubup.revert()

        # The first conflict is resolved by calling fix_ancestry_as_needed().
        upstreams_diverged, t_upstream_reverted = MP.fix_ancestry_as_needed(
            ubup, debp.branch)

        # The ancestry did diverge and needed to be fixed.
        self.assertEquals(upstreams_diverged, True)
        # The target upstream branch was more recent in this case and hence
        # was not reverted to the source upstream branch.
        self.assertEquals(t_upstream_reverted, False)

        # Try merging again.
        conflicts = ubup.merge_from_branch(
            debp.branch, to_revision=self.revid_debp_o_C)

        if not isinstance(conflicts, list):
            conflicts = ubup.conflicts()

        # And, voila, only the packaging branch conflict remains.
        conflict_paths = sorted([c.path for c in conflicts])
        self.assertEquals(conflict_paths, [u'debian/changelog'])

    def test_upstreams_not_diverged(self):
        """Non-diverging upstreams result in a normal merge.

        The debian and ubuntu upstream branches will not have diverged
        this time.

        The packaging branches will have a conflict in 'debian/changelog'.
        fix_ancestry_as_needed() will return as soon as establishing that
        the upstreams have not diverged.
        """
        ubuntup, debianp = self._setup_upstreams_not_diverged()

        # Attempt a plain merge first.
        conflicts = ubuntup.merge_from_branch(
            debianp.branch, to_revision=self.revid_debianp_C)

        if not isinstance(conflicts, list):
            conflicts = ubuntup.conflicts()

        # There is only a conflict in the 'debian/changelog' file.
        conflict_paths = sorted([c.path for c in conflicts])
        self.assertEquals(conflict_paths, [u'debian/changelog'])

        # Undo the failed merge.
        ubuntup.revert()

        # The conflict is *not* resolved by calling fix_ancestry_as_needed().
        upstreams_diverged, t_upstream_reverted = MP.fix_ancestry_as_needed(
            ubuntup, debianp.branch)

        # The ancestry did *not* diverge.
        self.assertEquals(upstreams_diverged, False)
        # The upstreams have not diverged, hence no need to fix/revert
        # either of them.
        self.assertEquals(t_upstream_reverted, False)

        # Try merging again.
        conflicts = ubuntup.merge_from_branch(
            debianp.branch, to_revision=self.revid_debianp_C)

        if not isinstance(conflicts, list):
            conflicts = ubuntup.conflicts()

        # The packaging branch conflict we saw above is still there.
        conflict_paths = sorted([c.path for c in conflicts])
        self.assertEquals(conflict_paths, [u'debian/changelog'])

    def _setup_debian_upstream_newer(self):
        r"""
        Set up the following test configuration (debian upstream newer).

        debian-upstream                 ,------------------H
                           A-----------B                    \
        ubuntu-upstream     \           \`-------G           \
                             \           \        \           \
        debian-packaging      \ ,---------D--------\-----------J
                               C                    \
        ubuntu-packaging        `----E---------------I

        where:
             - A = 1.0
             - B = 1.1
             - H = 1.10

             - G = 1.2

             - C = 1.0-1
             - D = 1.1-1
             - J = 1.10-1

             - E = 1.0-1ubuntu1
             - I = 1.2-0ubuntu1

        Please note that the debian and ubuntu *upstream* branches will
        have a conflict with respect to the file 'c'.
        """
        # Set up the debian upstream branch.
        name = 'debu-n'
        vdata = [
            ('upstream-1.0', ('a',), None, None),
            ('upstream-1.1', ('b',), None, None),
            ('upstream-1.10', ('c',), None, None),
            ]
        debu_n = self._setup_branch(name, vdata)

        # Set up the debian packaging branch.
        name = 'debp-n'
        debp_n = self.make_branch_and_tree(name)
        debp_n.pull(debu_n.branch, stop_revision=self.revid_debu_n_A)

        vdata = [
            ('1.0-1', ('debian/', 'debian/changelog'), None, None),
            ('1.1-1', ('o',), debu_n, self.revid_debu_n_B),
            ('1.10-1', ('p',), debu_n, self.revid_debu_n_C),
            ]
        self._setup_branch(name, vdata, debp_n, 'd')

        # Set up the ubuntu upstream branch.
        name = 'ubuu-o'
        ubuu_o = debu_n.controldir.sprout(
            name, revision_id=self.revid_debu_n_B).open_workingtree()

        vdata = [
            ('upstream-1.2', ('c',), None, None),
            ]
        self._setup_branch(name, vdata, ubuu_o)

        # Set up the ubuntu packaging branch.
        name = 'ubup-o'
        ubup_o = debu_n.controldir.sprout(
            name, revision_id=self.revid_debu_n_A).open_workingtree()

        vdata = [
            ('1.0-1ubuntu1', (), debp_n, self.revid_debp_n_A),
            ('1.2-0ubuntu1', (), ubuu_o, self.revid_ubuu_o_A),
            ]
        self._setup_branch(name, vdata, ubup_o, 'u')

        # Return the ubuntu and the debian packaging branches.
        return (ubup_o, debp_n, ubuu_o, debu_n)

    def _setup_debian_upstream_conflicts(self):
        r"""
        Set up the following test configuration (debian upstream newer).

        debian-upstream                 ,------------------H
                           A-----------B                    \
        ubuntu-upstream     \           \`-------G           \
                             \           \        \           \
        debian-packaging      \ ,---------D--------\-----------J
                               C                    \
        ubuntu-packaging        `----E---------------I

        where:
             - A = 1.0
             - B = 1.1
             - H = 1.10

             - G = 1.2

             - C = 1.0-1
             - D = 1.1-1
             - J = 1.10-1

             - E = 1.0-1ubuntu1
             - I = 1.2-0ubuntu1

        Please note that the debian upstream and the ubuntu packaging
        branches will have a conflict with respect to the file 'c'.
        """
        # Set up the debian upstream branch.
        name = 'debu-n'
        vdata = [
            ('upstream-1.0', ('a',), None, None),
            ('upstream-1.1', ('b',), None, None),
            ('upstream-1.10', ('c',), None, None),
            ]
        debu_n = self._setup_branch(name, vdata)

        # Set up the debian packaging branch.
        name = 'debp-n'
        debp_n = self.make_branch_and_tree(name)
        debp_n.pull(debu_n.branch, stop_revision=self.revid_debu_n_A)

        vdata = [
            ('1.0-1', ('debian/', 'debian/changelog'), None, None),
            ('1.1-1', ('o',), debu_n, self.revid_debu_n_B),
            ('1.10-1', ('p',), debu_n, self.revid_debu_n_C),
            ]
        self._setup_branch(name, vdata, debp_n, 'd')

        # Set up the ubuntu upstream branch.
        name = 'ubuu-o'
        ubuu_o = debu_n.controldir.sprout(
            name, revision_id=self.revid_debu_n_B).open_workingtree()

        vdata = [
            ('upstream-1.2', (), None, None),
            ]
        self._setup_branch(name, vdata, ubuu_o)

        # Set up the ubuntu packaging branch.
        name = 'ubup-o'
        ubup_o = debu_n.controldir.sprout(
            name, revision_id=self.revid_debu_n_A).open_workingtree()

        vdata = [
            ('1.0-1ubuntu1', (), debp_n, self.revid_debp_n_A),
            ('1.2-0ubuntu1', ('c',), ubuu_o, self.revid_ubuu_o_A),
            ]
        self._setup_branch(name, vdata, ubup_o, 'u')

        # Return the ubuntu and the debian packaging branches.
        return (ubup_o, debp_n, ubuu_o, debu_n)

    def _setup_debian_upstream_older(self):
        r"""
        Set up the following test configuration (debian upstream older).

        debian-upstream                 ,----H-------------.
                           A-----------B                    \
        ubuntu-upstream     \           \`-----------G       \
                             \           \            \       \
        debian-packaging      \ ,---------D------------\-------J
                               C                        \
        ubuntu-packaging        `----E-------------------I

        where:
             - A = 1.0
             - B = 1.1
             - H = 1.1.3

             - G = 2.1

             - C = 1.0-1
             - D = 1.1-1
             - J = 1.1.3-1

             - E = 1.0-1ubuntu1
             - I = 2.1-0ubuntu1

        Please note that the debian and ubuntu branches will have a conflict
        with respect to the file 'c'.
        """
        # Set up the debian upstream branch.
        name = 'debu-o'
        vdata = [
            ('upstream-1.0', ('a',), None, None),
            ('upstream-1.1', ('b',), None, None),
            ('upstream-1.1.3', ('c',), None, None),
            ]
        debu_o = self._setup_branch(name, vdata)

        # Set up the debian packaging branch.
        name = 'debp-o'
        debp_o = self.make_branch_and_tree(name)
        debp_o.pull(debu_o.branch, stop_revision=self.revid_debu_o_A)

        vdata = [
            ('1.0-1', ('debian/', 'debian/changelog'), None, None),
            ('1.1-1', ('o',), debu_o, self.revid_debu_o_B),
            ('1.1.3-1', ('p',), debu_o, self.revid_debu_o_C),
            ]
        self._setup_branch(name, vdata, debp_o, 'd')

        # Set up the ubuntu upstream branch.
        name = 'ubuu-n'
        ubuu_n = debu_o.controldir.sprout(
            name, revision_id=self.revid_debu_o_B).open_workingtree()

        vdata = [
            ('upstream-2.1', ('c',), None, None),
            ]
        self._setup_branch(name, vdata, ubuu_n)

        # Set up the ubuntu packaging branch.
        name = 'ubup-n'
        ubup_n = debu_o.controldir.sprout(
            name, revision_id=self.revid_debu_o_A).open_workingtree()

        vdata = [
            ('1.0-1ubuntu1', (), debp_o, self.revid_debp_o_A),
            ('2.1-0ubuntu1', (), ubuu_n, self.revid_ubuu_n_A),
            ]
        self._setup_branch(name, vdata, ubup_n, 'u')

        # Return the ubuntu and the debian packaging branches.
        return (ubup_n, debp_o, ubuu_n, debu_o)

    def _setup_upstreams_not_diverged(self):
        r"""
        Set up a test configuration where the usptreams have not diverged.

        debian-upstream                       .-----G
                           A-----------B-----H       \
        ubuntu-upstream     \           \     \       \
                             \           \     \       \
        debian-packaging      \ ,---------D-----\-------J
                               C                 \
        ubuntu-packaging        `----E------------I

        where:
             - A = 1.0
             - B = 1.1
             - H = 1.4

             - G = 2.2

             - C = 1.0-1
             - D = 1.1-1
             - J = 2.2-1

             - E = 1.0-1ubuntu1
             - I = 1.4-0ubuntu1

        Please note that there's only one shared upstream branch in this case.
        """
        # Set up the upstream branch.
        name = 'upstream'
        vdata = [
            ('upstream-1.0', ('a',), None, None),
            ('upstream-1.1', ('b',), None, None),
            ('upstream-1.4', ('c',), None, None),
            ]
        upstream = self._setup_branch(name, vdata)

        # Set up the debian upstream branch.
        name = 'dupstream'
        dupstream = upstream.controldir.sprout(name).open_workingtree()
        vdata = [
            ('upstream-2.2', (), None, None),
            ]
        dupstream = self._setup_branch(name, vdata, dupstream)

        # Set up the debian packaging branch.
        name = 'debianp'
        debianp = self.make_branch_and_tree(name)
        debianp.pull(dupstream.branch, stop_revision=self.revid_upstream_A)

        vdata = [
            ('1.0-1', ('debian/', 'debian/changelog'), None, None),
            ('1.1-1', ('o',), dupstream, self.revid_upstream_B),
            ('2.2-1', ('p',), dupstream, self.revid_dupstream_A),
            ]
        self._setup_branch(name, vdata, debianp, 'd')

        # Set up the ubuntu packaging branch.
        name = 'ubuntup'
        ubuntup = upstream.controldir.sprout(
            name, revision_id=self.revid_upstream_A).open_workingtree()

        vdata = [
            ('1.0-1ubuntu1', (), debianp, self.revid_debianp_A),
            ('1.4-0ubuntu1', (), upstream, self.revid_upstream_C),
            ]
        self._setup_branch(name, vdata, ubuntup, 'u')

        # Return the ubuntu and the debian packaging branches.
        return (ubuntup, debianp)

    def _setup_branch(self, name, vdata, tree=None, log_format=None):
        vids = list(string.ascii_uppercase)
        days = list(range(len(string.ascii_uppercase)))

        if tree is None:
            tree = self.make_branch_and_tree(name)

        tree.lock_write()
        self.addCleanup(tree.unlock)

        def revid_name(vid):
            return 'revid_%s_%s' % (name.replace('-', '_'), vid)

        def add_paths(paths):
            qpaths = ['%s/%s' % (name, path) for path in paths]
            self.build_tree(qpaths)
            tree.add(paths)

        def changelog(vdata, vid):
            result = ''
            day = days.pop(0)
            if isinstance(vdata, tuple):
                uver, dver = vdata[:2]
                ucle = _Ubuntu_changelog % (uver, vid, day)
                dcle = _Debian_changelog % (dver, vid, day)
                result = ucle + dcle
            else:
                if log_format == 'u':
                    result = _Ubuntu_changelog % (vdata, vid, day)
                elif log_format == 'd':
                    result = _Debian_changelog % (vdata, vid, day)

            return result

        def commit(msg, version):
            vid = vids.pop(0)
            if log_format is not None:
                cle = changelog(version, vid)
                p = '%s/work/%s/debian/changelog' % (self.test_base_dir, name)
                _prepend_log(cle, p)
            revid = tree.commit('%s: %s' % (vid, msg))
            setattr(self, revid_name(vid), revid)
            tree.branch.tags.set_tag(version, revid)

        def tree_nick(tree):
            return str(tree)[1:-1].split('/')[-1]

        for version, paths, utree, urevid in vdata:
            msg = ''
            if utree is not None:
                tree.merge_from_branch(utree.branch, to_revision=urevid)
                utree.branch.tags.merge_to(tree.branch.tags)
                if urevid is not None:
                    msg += 'Merged tree %s|%s. ' % (tree_nick(utree), urevid)
                else:
                    msg += 'Merged tree %s. ' % utree
            if paths is not None:
                add_paths(paths)
                msg += 'Added paths: %s. ' % str(paths)

            commit(msg, version)

        return tree
