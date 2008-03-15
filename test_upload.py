# Copyright (C) 2008 Canonical Ltd
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

import os


from bzrlib import (
    errors,
    revisionspec,
    tests,
    )
from bzrlib.tests import test_transport_implementations

from bzrlib.plugins.upload import cmd_upload


class TransportAdapter(
    test_transport_implementations.TransportTestProviderAdapter):
    """A tool to generate a suite testing all transports for a single test.

    We restrict the transports to the ones we want to support.
    """

    def _test_permutations(self):
        """Return a list of the klass, server_factory pairs to test."""
        result = []
        transport_modules =['bzrlib.transport.ftp',
                            'bzrlib.transport.sftp']
        for module in transport_modules:
            try:
                permutations = self.get_transport_test_permutations(
                    reduce(getattr, (module).split('.')[1:],
                           __import__(module)))
                for (klass, server_factory) in permutations:
                    scenario = (server_factory.__name__,
                        {"transport_class":klass,
                         "transport_server":server_factory})
                    result.append(scenario)
            except errors.DependencyNotPresent, e:
                # Continue even if a dependency prevents us 
                # from adding this test
                pass
        return result


def load_tests(standard_tests, module, loader):
    """Multiply tests for tranport implementations."""
    result = loader.suiteClass()
    adapter = TransportAdapter()
    for test in tests.iter_suite_tests(standard_tests):
        result.addTests(adapter.adapt(test))
    return result


class TestUpload(tests.TestCaseWithTransport):

    def _create_branch(self):
        tree = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/hello', 'foo')])
        tree.add('hello')
        tree.commit('setup')

        self.build_tree_contents([('branch/hello', 'bar'),
                                  ('branch/goodbye', 'baz')])
        tree.add('goodbye')
        tree.commit('setup')
        return tree

    def test_full_upload(self):
        self._create_branch()

        os.chdir('branch')
        upload = cmd_upload()
        up_url = self.get_transport('upload').external_url()

        upload.run(up_url, full=True)

        self.assertFileEqual('bar', '../upload/hello')
        self.assertFileEqual('baz', '../upload/goodbye')

    def test_incremental_upload(self):
        self._create_branch()

        os.chdir('branch')
        upload = cmd_upload()
        up_url = self.get_transport('upload').external_url()

        # Upload revision 1 only
        revspec = revisionspec.RevisionSpec.from_string('1')
        upload.run(up_url, revision=[revspec], full=True)

        self.assertFileEqual('foo', '../upload/hello')
        self.failIfExists('../upload/goodbye')

        # Upload current revision
        upload.run(up_url)

        self.assertFileEqual('bar','../upload/hello')
        self.assertFileEqual('baz', '../upload/goodbye')

    def test_invalid_revspec(self):
        self._create_branch()
        rev1 = revisionspec.RevisionSpec.from_string('1')
        rev2 = revisionspec.RevisionSpec.from_string('2')
        upload = cmd_upload()
        up_url = self.get_transport('upload').external_url()
        self.assertRaises(errors.BzrCommandError, upload.run,
                          up_url, revision=[rev1, rev2])

