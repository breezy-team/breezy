# Copyright (C) 2005, 2007, 2008, 2009 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""Black-box tests for bzr dpush."""


import os

from bzrlib.branch import (
    Branch,
    InterBranch,
    )
from bzrlib.bzrdir import (
    BzrDirFormat,
    )
from bzrlib.foreign import (
    ForeignBranch,
    ForeignRepository,
    )
from bzrlib.repository import (
    Repository,
    )
from bzrlib.tests.blackbox import (
    ExternalBase,
    )
from bzrlib.tests.test_foreign import (
    DummyForeignVcsDirFormat,
    InterToDummyVcsBranch,
    )


class TestDpush(ExternalBase):

    def setUp(self):
        BzrDirFormat.register_control_format(DummyForeignVcsDirFormat)
        InterBranch.register_optimiser(InterToDummyVcsBranch)
        self.addCleanup(self.unregister_format)
        super(TestDpush, self).setUp()

    def unregister_format(self):
        try:
            BzrDirFormat.unregister_control_format(DummyForeignVcsDirFormat)
        except ValueError:
            pass
        InterBranch.unregister_optimiser(InterToDummyVcsBranch)

    def make_dummy_builder(self, relpath):
        builder = self.make_branch_builder(relpath, 
                format=DummyForeignVcsDirFormat())
        builder.build_snapshot('revid', None, 
            [('add', ('', 'TREE_ROOT', 'directory', None)),
             ('add', ('foo', 'fooid', 'file', 'bar'))])
        return builder

    def test_dpush_native(self):
        target_tree = self.make_branch_and_tree("dp")
        source_tree = self.make_branch_and_tree("dc")
        output, error = self.run_bzr("dpush -d dc dp", retcode=3)
        self.assertEquals("", output)
        self.assertContainsRe(error, 'in the same VCS, lossy push not necessary. Please use regular push.')

    def test_dpush(self):
        branch = self.make_dummy_builder('d').get_branch()

        dc = branch.bzrdir.sprout('dc', force_new_repo=True)
        self.build_tree(("dc/foo", "blaaaa"))
        dc.open_workingtree().commit('msg')

        output, error = self.run_bzr("dpush -d dc d")
        self.assertEquals(error, "Pushed up to revision 2.\n")
        self.check_output("", "status dc")

    def test_dpush_new(self):
        branch = self.make_dummy_builder('d').get_branch()

        dc = branch.bzrdir.sprout('dc', force_new_repo=True)
        self.build_tree_contents([("dc/foofile", "blaaaa")])
        dc_tree = dc.open_workingtree()
        dc_tree.add("foofile")
        dc_tree.commit("msg")

        self.check_output("", "dpush -d dc d")
        self.check_output("2\n", "revno dc")
        self.check_output("", "status dc")

    def test_dpush_wt_diff(self):
        branch = self.make_dummy_builder('d').get_branch()

        dc = branch.bzrdir.sprout('dc', force_new_repo=True)
        self.build_tree_contents([("dc/foofile", "blaaaa")])
        dc_tree = dc.open_workingtree()
        dc_tree.add("foofile")
        newrevid = dc_tree.commit('msg')

        self.build_tree_contents([("dc/foofile", "blaaaal")])
        self.check_output("", "dpush -d dc d")
        self.assertFileEqual("blaaaal", "dc/foofile")
        self.check_output('modified:\n  foofile\n', "status dc")

    def test_diverged(self):
        builder = self.make_dummy_builder('d')

        branch = builder.get_branch()

        dc = branch.bzrdir.sprout('dc', force_new_repo=True)
        dc_tree = dc.open_workingtree()

        self.build_tree_contents([("dc/foo", "bar")])
        dc_tree.commit('msg1')

        builder.build_snapshot('revid2', None,
          [('modify', ('fooid', 'blie'))])

        output, error = self.run_bzr("dpush -d dc d", retcode=3)
        self.assertEquals(output, "")
        self.assertContainsRe(error, "have diverged")
