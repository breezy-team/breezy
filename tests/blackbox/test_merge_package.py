#    test_builddeb.py -- Blackbox tests for builddeb.
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
#

from .....merge import Merger
import os
import string

from ..... import (
    errors,
    )
from .....tests import TestNotApplicable
from ... import pre_merge_fix_ancestry
from .. import BuilddebTestCase


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
    with open(path, 'r') as f:
        content = f.read()
    with open(path, 'w') as fh:
        fh.write(text+content)


class TestMergePackageBB(BuilddebTestCase):

    def test_merge_package_shared_rev_conflict(self):
        """Source upstream conflicts with target packaging -> Error.

        The debian upstream and the ubuntu packaging branches will differ
        with respect to the content of the file 'c'.

        The conflict cannot be resolved by fix_ancestry_as_needed().
        The `SharedUpstreamConflictsWithTargetPackaging` exception is
        thrown instead.
        """
        target, _source = self.make_conflicting_branches_setup()
        os.chdir('ubup-o')
        merge_source = '../debp-n'
        self.run_bzr_error(
            ['2 conflicts encountered.'],
            'merge %s' % merge_source, retcode=1)

    def test_pre_merge_hook_shared_rev_conflict(self):
        """Source upstream conflicts with target packaging -> Error.

        The debian upstream and the ubuntu packaging branches will differ
        with respect to the content of the file 'c'.

        The conflict cannot be resolved by fix_ancestry_as_needed().
        The `SharedUpstreamConflictsWithTargetPackaging` exception is
        thrown instead.
        """
        target, _source = self.make_conflicting_branches_setup()
        os.chdir('ubup-o')
        merge_source = '../debp-n'
        try:
            Merger.hooks.install_named_hook(
                "pre_merge", pre_merge_fix_ancestry, "fix ancestry")
        except errors.UnknownHook:
            raise TestNotApplicable("pre_merge hook requires bzr 2.5")
        self.run_bzr_error(
            ['branches for the merge source and target have diverged'],
            'merge %s' % merge_source)

    def make_conflicting_branches_setup(self):
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
           - H = 2.0

           - G = 1.1.2

           - C = 1.0-1
           - D = 1.1-1
           - J = 2.0-1

           - E = 1.0-1ubuntu1
           - I = 1.1.2-0ubuntu1

        Please note that the debian upstream and the ubuntu packaging
        branches will have a conflict with respect to the file 'c'.
        """
        # Set up the debian upstream branch.
        name = 'debu-n'
        vdata = [
            ('upstream-1.0', ('a',), None, None),
            ('upstream-1.1', ('b',), None, None),
            ('upstream-2.0', ('c',), None, None)]
        debu_n = self._setup_branch(name, vdata)

        # Set up the debian packaging branch.
        name = 'debp-n'
        debp_n = self.make_branch_and_tree(name)
        debp_n.pull(debu_n.branch, stop_revision=self.revid_debu_n_A)

        vdata = [
            ('1.0-1', ('debian/', 'debian/changelog'), None, None),
            ('1.1-1', ('o',), debu_n, self.revid_debu_n_B),
            ('2.0-1', ('p',), debu_n, self.revid_debu_n_C)]
        self._setup_branch(name, vdata, debp_n, 'd')

        # Set up the ubuntu upstream branch.
        name = 'ubuu-o'
        ubuu_o = debu_n.controldir.sprout(
            name, revision_id=self.revid_debu_n_B).open_workingtree()

        vdata = [('upstream-1.1.2', (), None, None)]
        self._setup_branch(name, vdata, ubuu_o)

        # Set up the ubuntu packaging branch.
        name = 'ubup-o'
        ubup_o = debu_n.controldir.sprout(
            name, revision_id=self.revid_debu_n_A).open_workingtree()

        vdata = [
            ('1.0-1ubuntu1', (), debp_n, self.revid_debp_n_A),
            ('1.1.2-0ubuntu1', ('c',), ubuu_o, self.revid_ubuu_o_A)]
        self._setup_branch(name, vdata, ubup_o, 'u')

        # Return the ubuntu and the debian packaging branches.
        return (ubup_o, debp_n)

    def _setup_branch(self, name, vdata, tree=None, log_format=None):
        vids = list(string.ascii_uppercase)
        days = list(range(len(string.ascii_uppercase)))

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

        with tree.lock_write():
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
