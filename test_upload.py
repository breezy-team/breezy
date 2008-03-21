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
    bzrdir,
    errors,
    revisionspec,
    tests,
    transport,
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

    def make_local_branch(self):
        t = transport.get_transport('branch')
        t.ensure_base()
        branch = bzrdir.BzrDir.create_branch_convenience(
            t.base,
            format=bzrdir.format_registry.make_bzrdir('default'),
            force_new_tree=False)
        tree = branch.bzrdir.create_workingtree()
        return tree

    def build_branch_contents(self, reltree, relpath='branch/'):
        """Build the tree content at relpath."""
        abstree = []
        for relitem in reltree:
            abstree.append((relpath + relitem[0],) + relitem[1:])
        self.build_tree_contents(abstree)

    def assertUpFileEqual(self, content, path, relpath='upload/'):
        self.assertFileEqual(content, relpath + path)

    def failIfUpFileExists(self, path, relpath='upload/'):
        self.failIfExists(relpath + path)

    def full_upload(self, *args, **kwargs):
        upload = cmd_upload()
        up_url = self.get_transport('upload').external_url()
        if kwargs.get('working_dir', None) is None:
            kwargs['working_dir'] = 'branch'
        kwargs['full'] = True
        upload.run(up_url, *args, **kwargs)

    def incremental_upload(self, *args, **kwargs):
        upload = cmd_upload()
        up_url = self.get_transport('upload').external_url()
        if kwargs.get('working_dir', None) is None:
            kwargs['working_dir'] = 'branch'
        upload.run(up_url, *args, **kwargs)

    def _add_hello(self, tree):
        self.build_branch_contents([('hello', 'foo')])
        tree.add('hello')
        tree.commit('add hello')

    def _modify_hello_add_goodbye(self, tree):
        self.build_branch_contents([('hello', 'bar'),
                                  ('dir/',),
                                  ('dir/goodbye', 'baz')])
        tree.add('dir')
        tree.add('dir/goodbye')
        tree.commit('modify hello, add goodbye')

    def test_full_upload(self):
        tree = self.make_local_branch()
        self._add_hello(tree)
        self._modify_hello_add_goodbye(tree)

        self.full_upload()

        self.assertUpFileEqual('bar', 'hello')
        self.assertUpFileEqual('baz', 'dir/goodbye')

    def test_incremental_upload(self):
        tree = self.make_local_branch()
        self._add_hello(tree)
        self._modify_hello_add_goodbye(tree)

        # Upload revision 1 only
        revspec = revisionspec.RevisionSpec.from_string('1')
        self.full_upload(revision=[revspec])

        self.assertUpFileEqual('foo', 'hello')
        self.failIfUpFileExists('upload/dir/goodbye')

        # Upload current revision
        self.incremental_upload()

        self.assertUpFileEqual('bar', 'hello')
        self.assertUpFileEqual('baz', 'dir/goodbye')

    def test_invalid_revspec(self):
        tree = self.make_local_branch()
        rev1 = revisionspec.RevisionSpec.from_string('1')
        rev2 = revisionspec.RevisionSpec.from_string('2')

        self.full_upload()

        self.assertRaises(errors.BzrCommandError,
                          self.incremental_upload, revision=[rev1, rev2])

