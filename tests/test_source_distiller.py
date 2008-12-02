#    test_source_distiller.py -- Getting the source to build from a branch
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


from bzrlib.errors import (
        ObjectNotLocked,
        FileExists,
        )
from bzrlib.tests import TestCaseWithTransport

from bzrlib.plugins.builddeb.source_distiller import (
        NativeSourceDistiller,
        )


class TestNativeSourceDistiller(TestCaseWithTransport):

    def test_distill_target_exists(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        sd = NativeSourceDistiller(wt)
        self.build_tree(['target/'])
        self.assertRaises(FileExists, sd.distill, 'target')

    def test_distill_revision_tree(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(['a'])
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add(['a'])
        revid = wt.commit("one")
        rev_tree = wt.basis_tree()
        sd = NativeSourceDistiller(rev_tree)
        sd.distill('target')
        self.failUnlessExists('target')
        self.failUnlessExists('target/a')
