# Copyright (C) 2006 by Canonical Ltd
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

"""Test read_bundle works properly across various transports."""

import cStringIO
import os

import bzrlib.bundle
from bzrlib.bundle.serializer import write_bundle
import bzrlib.bzrdir
import bzrlib.errors as errors
from bzrlib.tests import TestCaseInTempDir
import bzrlib.transport
from bzrlib.transport.memory import MemoryTransport
import bzrlib.urlutils


# jam 20060615 Originally I thought I should use TestCaseWithTransport
#       but it turns out that doesn't play well with the transport adapter
class TestReadBundleFromURL(TestCaseInTempDir):
    """Test that read_bundle works properly across multiple transports"""

    def setUp(self):
        super(TestReadBundleFromURL, self).setUp()
        self._server = self.transport_server()
        self._server.setUp()
        self._transport = None

    def tearDown(self):
        self._transport = None
        self._server.tearDown()
        super(TestReadBundleFromURL, self).tearDown()
        
    def get_transport(self):
        """Return a connected transport to the local directory."""
        base_url = self._server.get_url()
        t = bzrlib.transport.get_transport(base_url)
        if not isinstance(t, self.transport_class):
            # we want to make sure to construct one particular class, even if
            # there are several available implementations of this transport;
            # therefore construct it by hand rather than through the regular
            # get_transport method
            t = self.transport_class(base_url)
        return t

    def get_url(self, relpath=''):
        return bzrlib.urlutils.join(self._server.get_url(), relpath)

    def create_test_bundle(self):
        # Can't use self.get_transport() because that asserts that 
        # it is not readonly, so just skip tests where the server is readonly
        self._transport = self.get_transport()
        #if isinstance(self._transport, MemoryTransport):
        #    return None
        self.build_tree(['tree/', 'tree/a', 'tree/subdir/'])

        format = bzrlib.bzrdir.BzrDirFormat.get_default_format()


        bzrdir = format.initialize('tree')
        repo = bzrdir.create_repository()
        branch = repo.bzrdir.create_branch()
        wt = branch.bzrdir.create_workingtree()

        wt.add(['a', 'subdir/'])
        wt.commit('new project', rev_id='commit-1')

        out = cStringIO.StringIO()
        rev_ids = write_bundle(wt.branch.repository,
                               wt.last_revision(), None, out)
        out.seek(0)
        if self._transport.is_readonly():
            f = open('test_bundle', 'wb')
            f.write(out.getvalue())
            f.close()
        else:
            self._transport.put('test_bundle', out)
            self.log('Put to: %s', self.get_url('test_bundle'))
        return wt

    def test_read_bundle_from_url(self):
        wt = self.create_test_bundle()
        if wt is None:
            return

        info = bzrlib.bundle.read_bundle_from_url(
                    self.get_url('test_bundle'))
        bundle_tree = info.revision_tree(wt.branch.repository, info.target)
        self.assertEqual('commit-1', bundle_tree.revision_id)

    def test_read_fail(self):
        # Trying to read from a directory, or non-bundle file
        # should fail with NotABundle
        wt = self.create_test_bundle()
        if wt is None:
            return

        self.assertRaises(errors.NotABundle, 
            bzrlib.bundle.read_bundle_from_url, 
            self.get_url('tree'))
        self.assertRaises(errors.NotABundle, 
            bzrlib.bundle.read_bundle_from_url, 
            self.get_url('tree/a'))
