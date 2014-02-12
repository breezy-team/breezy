# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
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

"""Tests for bzr-git's object store."""


from dulwich.tests.test_object_store import PackBasedObjectStoreTests

from bzrlib.tests import TestCaseWithTransport

from bzrlib.plugins.git.transportgit import TransportObjectStore


class TransportObjectStoreTests(PackBasedObjectStoreTests, TestCaseWithTransport):

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.store = TransportObjectStore.init(self.get_transport())

    def tearDown(self):
        PackBasedObjectStoreTests.tearDown(self)
        TestCaseWithTransport.tearDown(self)

# FIXME: Unfortunately RefsContainerTests requires on a specific set of refs existing.

# class TransportRefContainerTests(RefsContainerTests, TestCaseWithTransport):
#
#    def setUp(self):
#        TestCaseWithTransport.setUp(self)
#        self._refs = TransportRefsContainer(self.get_transport())

