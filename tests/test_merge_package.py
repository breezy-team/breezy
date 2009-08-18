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

import os
import random
import string
import unittest

from bzrlib.errors import ConflictsInTree
from bzrlib.merge import WeaveMerger
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

    def test_latest_upstream_versions(self):
        ubup_o, debp_n = self._setup_debian_un()

        # Ubuntu upstream.
        self.assertEquals(
            MP._latest_version(ubup_o.branch).upstream_version, '1.1.2')
        # Debian upstream.
        self.assertEquals(
            MP._latest_version(debp_n.branch).upstream_version, '2.0')

    def test_debian_un(self):
        """Make sure fix_ancestry_as_needed() resolves upstream conflicts.

        The debian and ubuntu upstream branches will differ with regard to
        the content of the file 'c'.

        Furthermore the respective packaging branches will have a text
        conflict in 'debian/changelog'.

        The upstream conflict will be resolved by fix_ancestry_as_needed().
        """
        ubup_o, debp_n = self._setup_debian_un()
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
        MP.fix_ancestry_as_needed(ubup_o, debp_n.branch)

        conflicts = ubup_o.merge_from_branch(
            debp_n.branch, to_revision=self.revid_debp_n_C)

        # And, voila, only the packaging branch conflict remains.
        self.assertEquals(conflicts, 1)
        conflict_paths = sorted([c.path for c in ubup_o.conflicts()])
        self.assertEquals(conflict_paths, [u'debian/changelog'])

    def _setup_debian_un(self):
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
        name = 'debu-n'
        vdata = [
            ('upstream-1.0', ('a',), None, None),
            ('upstream-1.1', ('b',), None, None),
            ('upstream-2.0', ('c',), None, None),
            ]
        debu_n = self._setup_branch(name, vdata)

        name = 'debp-n'
        debp_n = self.make_branch_and_tree(name)
        debp_n.pull(debu_n.branch, stop_revision=self.revid_debu_n_A)

        vdata = [
            ('1.0-1', ('debian/', 'debian/changelog'), None, None),
            ('1.1-1', ('o',), debu_n, self.revid_debu_n_B),
            ('2.0-1', ('p',), debu_n, self.revid_debu_n_C),
            ]
        self._setup_branch(name, vdata, debp_n, 'd')

        name = 'ubuu-o'
        ubuu_o = debu_n.bzrdir.sprout(
            name, revision_id=self.revid_debu_n_B).open_workingtree()

        vdata = [
            ('upstream-1.1.2', ('c',), None, None),
            ]
        self._setup_branch(name, vdata, ubuu_o)

        name = 'ubup-o'
        ubup_o = debu_n.bzrdir.sprout(
            name, revision_id=self.revid_debu_n_A).open_workingtree()

        vdata = [
            ('1.0-1ubuntu1', (), debp_n, self.revid_debp_n_A),
            ('1.1.2-0ubuntu1', (), ubuu_o, self.revid_ubuu_o_A),
            ]
        self._setup_branch(name, vdata, ubup_o, 'u')

        return (ubup_o, debp_n)

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
            revid = tree.commit('%s: %s' % (vid, msg), rev_id='%s-%s' % (name, vid))
            setattr(self, revid_name(vid), revid)
            tree.branch.tags.set_tag(version, revid)

        def tree_nick(tree):
            return str(tree)[1:-1].split('/')[-1]
            
        for version, paths, utree, urevid in vdata:
            msg = ''
            if utree is not None:
                tree.merge_from_branch(
                    utree.branch, to_revision=urevid, merge_type=WeaveMerger)
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
    unittest.main()
