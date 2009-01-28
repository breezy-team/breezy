# Copyright (C) 2005, 2007, 2008 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Black-box tests for bzr dpush."""

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDirFormat
from bzrlib.repository import Repository
from bzrlib.foreign import ForeignBranch, ForeignRepository
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests.test_foreign import DummyForeignVcsBzrDirFormat

class TestDpush(ExternalBase):

    def setUp(self):
        super(TestDpush, self).setUp()
        BzrDirFormat.register_control_format(DummyForeignVcsBzrDirFormat)

    def tearDown(self):
        super(TestDpush, self).tearDown()
        try:
            BzrDirFormat.unregister_control_format(DummyForeignVcsBzrDirFormat)
        except ValueError:
            pass

    def test_dpush_empty(self):
        tree = self.make_branch_and_tree("dp", format=DummyForeignVcsBzrDirFormat)
        self.run_bzr("init --rich-root-pack dc")
        os.chdir("dc")
        self.run_bzr("dpush %s" % repos_url)

    def test_dpush(self):
        tree = self.make_branch_and_tree("d", format=DummyForeignVcsBzrDirFormat)

        self.build_tree(("d/foo", "bar"))
        tree.add("foo")
        tree.commit("msg")

        self.run_bzr("branch %s dc" % repos_url)
        self.build_tree(("dc/foo", "blaaaa"))
        self.run_bzr("commit -m msg dc")
        self.run_bzr("dpush -d dc %s" % repos_url)
        self.check_output("", "status dc")

    def test_dpush_new(self):
        tree = self.make_branch_and_tree("d", format=DummyForeignVcsBzrDirFormat)

        self.build_tree(("d/foo", "bar"))
        tree.add("foo")
        tree.commit("msg")

        self.run_bzr("branch %s dc" % repos_url)
        self.build_tree(("dc/foofile", "blaaaa"))
        self.run_bzr("add dc/foofile")
        self.run_bzr("commit -m msg dc")
        self.run_bzr("dpush -d dc %s" % repos_url)
        self.check_output("3\n", "revno dc")
        self.check_output("", "status dc")

    def test_dpush_wt_diff(self):
        tree = self.make_branch_and_tree("d", format=DummyForeignVcsBzrDirFormat)
        
        self.build_tree(("d/foo", "bar"))
        tree.add("foo")
        tree.commit("msg")

        self.run_bzr("branch %s dc" % repos_url)
        self.build_tree({"dc/foofile": "blaaaa"})
        self.run_bzr("add dc/foofile")
        self.run_bzr("commit -m msg dc")
        self.build_tree({"dc/foofile": "blaaaal"})
        self.run_bzr("dpush -d dc %s" % repos_url)
        self.check_output('modified:\n  foofile\n', "status dc")
