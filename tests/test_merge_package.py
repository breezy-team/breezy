#!/usr/bin/env python
# -*- coding: iso-8859-15 -*-
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

import string
import unittest

from bzrlib.errors import ConflictsInTree
from bzrlib.tests import TestCaseWithTransport

from bzrlib.plugins.builddeb import merge_package as MP

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
    fh = open(path, 'wb')
    fh.write(text+content)
    fh.close()


class MergePackageTests(TestCaseWithTransport):

    def _latest_version(self, branch):
        try:
            branch.lock_read()
            result = MP._latest_version(branch).upstream_version
        finally:
            branch.unlock()
        return result

    def test_latest_upstream_versions(self):
        """Check correctness of upstream version computation."""
        ubup_o, debp_n = self._setup_debian_upstrem_newer()
        # Ubuntu upstream.
        self.assertEquals(
            self._latest_version(ubup_o.branch), '1.1.2')
        # Debian upstream.
        self.assertEquals(
            self._latest_version(debp_n.branch), '2.0')

        ubuntup, debianp = self._setup_upstreams_not_diverged()
        # Ubuntu upstream.
        self.assertEquals(
            self._latest_version(ubuntup.branch), '1.4')
        # Debian upstream.
        self.assertEquals(
            self._latest_version(debianp.branch), '2.2')

    def test_debian_upstream_newer(self):
        """Diverging upstreams (debian newer) don't cause merge conflicts.

        The debian and ubuntu upstream branches will differ with regard to
        the content of the file 'c'.

        Furthermore the respective packaging branches will have a text
        conflict in 'debian/changelog'.

        The upstream conflict will be resolved by fix_ancestry_as_needed().
        Please note that the debian ancestry is more recent.
        """
        ubup_o, debp_n = self._setup_debian_upstrem_newer()

        # Attempt a plain merge first.
        conflicts = ubup_o.merge_from_branch(
            debp_n.branch, to_revision=self.revid_debp_n_C)

        # There are two conflicts in the 'c' and the 'debian/changelog' files
        # respectively.
        self.assertEquals(conflicts, 2)
        conflict_paths = sorted([c.path for c in ubup_o.conflicts()])
        self.assertEquals(conflict_paths, [u'c.moved', u'debian/changelog'])

        # Undo the failed merge.
        ubup_o.revert()

        # The first conflict is resolved by calling fix_ancestry_as_needed().
        upstreams_diverged, t_upstream_reverted = MP.fix_ancestry_as_needed(ubup_o, debp_n.branch)

        # The ancestry did diverge and needed to be fixed.
        self.assertEquals(upstreams_diverged, True)
        # The (temporary) target upstream branch had to be reverted to the
        # source upstream branch since the latter was more recent.
        self.assertEquals(t_upstream_reverted, True)

        # Try merging again.
        conflicts = ubup_o.merge_from_branch(
            debp_n.branch, to_revision=self.revid_debp_n_C)

        # And, voila, only the packaging branch conflict remains.
        self.assertEquals(conflicts, 1)
        conflict_paths = sorted([c.path for c in ubup_o.conflicts()])
        self.assertEquals(conflict_paths, [u'debian/changelog'])

    def test_debian_upstream_older(self):
        """Diverging upstreams (debian older) don't cause merge conflicts.

        The debian and ubuntu upstream branches will differ with regard to
        the content of the file 'c'.

        Furthermore the respective packaging branches will have a text
        conflict in 'debian/changelog'.

        The upstream conflict will be resolved by fix_ancestry_as_needed().
        Please note that the debian ancestry is older in this case.
        """
        ubup_n, debp_o = self._setup_debian_upstream_older()

        # Attempt a plain merge first.
        conflicts = ubup_n.merge_from_branch(
            debp_o.branch, to_revision=self.revid_debp_o_C)

        # There are two conflicts in the 'c' and the 'debian/changelog' files
        # respectively.
        self.assertEquals(conflicts, 2)
        conflict_paths = sorted([c.path for c in ubup_n.conflicts()])
        self.assertEquals(conflict_paths, [u'c.moved', u'debian/changelog'])

        # Undo the failed merge.
        ubup_n.revert()

        # The first conflict is resolved by calling fix_ancestry_as_needed().
        upstreams_diverged, t_upstream_reverted = MP.fix_ancestry_as_needed(ubup_n, debp_o.branch)

        # The ancestry did diverge and needed to be fixed.
        self.assertEquals(upstreams_diverged, True)
        # The target upstream branch was more recent in this case and hence
        # was not reverted to the source upstream branch.
        self.assertEquals(t_upstream_reverted, False)

        # Try merging again.
        conflicts = ubup_n.merge_from_branch(
            debp_o.branch, to_revision=self.revid_debp_o_C)

        # And, voila, only the packaging branch conflict remains.
        self.assertEquals(conflicts, 1)
        conflict_paths = sorted([c.path for c in ubup_n.conflicts()])
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

        # There is only a conflict in the 'debian/changelog' file.
        self.assertEquals(conflicts, 1)
        conflict_paths = sorted([c.path for c in ubuntup.conflicts()])
        self.assertEquals(conflict_paths, [u'debian/changelog'])

        # Undo the failed merge.
        ubuntup.revert()

        # The conflict is *not* resolved by calling fix_ancestry_as_needed().
        upstreams_diverged, t_upstream_reverted = MP.fix_ancestry_as_needed(ubuntup, debianp.branch)

        # The ancestry did *not* diverge.
        self.assertEquals(upstreams_diverged, False)
        # The upstreams have not diverged, hence no need to fix/revert 
        # either of them.
        self.assertEquals(t_upstream_reverted, False)

        # Try merging again.
        conflicts = ubuntup.merge_from_branch(
            debianp.branch, to_revision=self.revid_debianp_C)

        # The packaging branch conflict we saw above is still there.
        self.assertEquals(conflicts, 1)
        conflict_paths = sorted([c.path for c in ubuntup.conflicts()])
        self.assertEquals(conflict_paths, [u'debian/changelog'])

    def _setup_debian_upstrem_newer(self):
        """
        Set up the following test configuration (debian upstrem newer).

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
             - H = 2.0

             - G = 1.1.2

             - C = 1.0-1
             - D = 1.1-1
             - J = 2.0-1

             - E = 1.0-1ubuntu1
             - I = 1.1.2-0ubuntu1

        Please note that the debian and ubuntu branches will have a conflict
        with respect to the file 'c'.
        """
        # Set up the debian upstream branch.
        name = 'debu-n'
        vdata = [
            ('upstream-1.0', ('a',), None, None),
            ('upstream-1.1', ('b',), None, None),
            ('upstream-2.0', ('c',), None, None),
            ]
        debu_n = self._setup_branch(name, vdata)

        # Set up the debian packaging branch.
        name = 'debp-n'
        debp_n = self.make_branch_and_tree(name)
        debp_n.pull(debu_n.branch, stop_revision=self.revid_debu_n_A)

        vdata = [
            ('1.0-1', ('debian/', 'debian/changelog'), None, None),
            ('1.1-1', ('o',), debu_n, self.revid_debu_n_B),
            ('2.0-1', ('p',), debu_n, self.revid_debu_n_C),
            ]
        self._setup_branch(name, vdata, debp_n, 'd')

        # Set up the ubuntu upstream branch.
        name = 'ubuu-o'
        ubuu_o = debu_n.bzrdir.sprout(
            name, revision_id=self.revid_debu_n_B).open_workingtree()

        vdata = [
            ('upstream-1.1.2', ('c',), None, None),
            ]
        self._setup_branch(name, vdata, ubuu_o)

        # Set up the ubuntu packaging branch.
        name = 'ubup-o'
        ubup_o = debu_n.bzrdir.sprout(
            name, revision_id=self.revid_debu_n_A).open_workingtree()

        vdata = [
            ('1.0-1ubuntu1', (), debp_n, self.revid_debp_n_A),
            ('1.1.2-0ubuntu1', (), ubuu_o, self.revid_ubuu_o_A),
            ]
        self._setup_branch(name, vdata, ubup_o, 'u')

        # Return the ubuntu and the debian packaging branches.
        return (ubup_o, debp_n)

    def _setup_debian_upstream_older(self):
        """
        Set up the following test configuration (debian upstrem older).

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
        ubuu_n = debu_o.bzrdir.sprout(
            name, revision_id=self.revid_debu_o_B).open_workingtree()

        vdata = [
            ('upstream-2.1', ('c',), None, None),
            ]
        self._setup_branch(name, vdata, ubuu_n)

        # Set up the ubuntu packaging branch.
        name = 'ubup-n'
        ubup_n = debu_o.bzrdir.sprout(
            name, revision_id=self.revid_debu_o_A).open_workingtree()

        vdata = [
            ('1.0-1ubuntu1', (), debp_o, self.revid_debp_o_A),
            ('2.1-0ubuntu1', (), ubuu_n, self.revid_ubuu_n_A),
            ]
        self._setup_branch(name, vdata, ubup_n, 'u')

        # Return the ubuntu and the debian packaging branches.
        return (ubup_n, debp_o)

    def _setup_upstreams_not_diverged(self):
        """
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
        dupstream = upstream.bzrdir.sprout(name).open_workingtree()
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
        ubuntup = upstream.bzrdir.sprout(
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
        days = range(len(string.ascii_uppercase))

        if tree is None:
            tree = self.make_branch_and_tree(name)

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


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(MergePackageTests)
    unittest.TextTestRunner(verbosity=2).run(suite)

