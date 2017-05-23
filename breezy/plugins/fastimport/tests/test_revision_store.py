# Copyright (C) 2008, 2009 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Direct tests of the revision_store classes."""

from bzrlib import (
    branch,
    errors,
    inventory,
    osutils,
    tests,
    )

from bzrlib.plugins.fastimport import (
    revision_store,
    )
from bzrlib.plugins.fastimport.tests import (
    FastimportFeature,
    )


class Test_TreeShim(tests.TestCase):

    _test_needs_features = [FastimportFeature]

    def invAddEntry(self, inv, path, file_id=None):
        if path.endswith('/'):
            path = path[:-1]
            kind = 'directory'
        else:
            kind = 'file'
        parent_path, basename = osutils.split(path)
        parent_id = inv.path2id(parent_path)
        inv.add(inventory.make_entry(kind, basename, parent_id, file_id))

    def make_trivial_basis_inv(self):
        basis_inv = inventory.Inventory('TREE_ROOT')
        self.invAddEntry(basis_inv, 'foo', 'foo-id')
        self.invAddEntry(basis_inv, 'bar/', 'bar-id')
        self.invAddEntry(basis_inv, 'bar/baz', 'baz-id')
        return basis_inv

    def test_id2path_no_delta(self):
        basis_inv = self.make_trivial_basis_inv()
        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=[], content_provider=None)
        self.assertEqual('', shim.id2path('TREE_ROOT'))
        self.assertEqual('foo', shim.id2path('foo-id'))
        self.assertEqual('bar', shim.id2path('bar-id'))
        self.assertEqual('bar/baz', shim.id2path('baz-id'))
        self.assertRaises(errors.NoSuchId, shim.id2path, 'qux-id')

    def test_id2path_with_delta(self):
        basis_inv = self.make_trivial_basis_inv()
        foo_entry = inventory.make_entry('file', 'foo2', 'TREE_ROOT', 'foo-id')
        inv_delta = [('foo', 'foo2', 'foo-id', foo_entry),
                     ('bar/baz', None, 'baz-id', None),
                    ]

        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=inv_delta,
                                        content_provider=None)
        self.assertEqual('', shim.id2path('TREE_ROOT'))
        self.assertEqual('foo2', shim.id2path('foo-id'))
        self.assertEqual('bar', shim.id2path('bar-id'))
        self.assertRaises(errors.NoSuchId, shim.id2path, 'baz-id')

    def test_path2id(self):
        basis_inv = self.make_trivial_basis_inv()
        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=[], content_provider=None)
        self.assertEqual('TREE_ROOT', shim.path2id(''))
        # We don't want to ever give a wrong value, so for now we just raise
        # NotImplementedError
        self.assertRaises(NotImplementedError, shim.path2id, 'bar')

    def test_get_file_with_stat_content_in_stream(self):
        basis_inv = self.make_trivial_basis_inv()

        def content_provider(file_id):
            return 'content of\n' + file_id + '\n'

        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=[],
                                        content_provider=content_provider)
        f_obj, stat_val = shim.get_file_with_stat('baz-id')
        self.assertIs(None, stat_val)
        self.assertEqualDiff('content of\nbaz-id\n', f_obj.read())

    # TODO: Test when the content isn't in the stream, and we fall back to the
    #       repository that was passed in

    def test_get_symlink_target(self):
        basis_inv = self.make_trivial_basis_inv()
        ie = inventory.make_entry('symlink', 'link', 'TREE_ROOT', 'link-id')
        ie.symlink_target = u'link-target'
        basis_inv.add(ie)
        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=[], content_provider=None)
        self.assertEqual(u'link-target', shim.get_symlink_target('link-id'))

    def test_get_symlink_target_from_delta(self):
        basis_inv = self.make_trivial_basis_inv()
        ie = inventory.make_entry('symlink', 'link', 'TREE_ROOT', 'link-id')
        ie.symlink_target = u'link-target'
        inv_delta = [(None, 'link', 'link-id', ie)]
        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=inv_delta,
                                        content_provider=None)
        self.assertEqual(u'link-target', shim.get_symlink_target('link-id'))

    def test__delta_to_iter_changes(self):
        basis_inv = self.make_trivial_basis_inv()
        foo_entry = inventory.make_entry('file', 'foo2', 'bar-id', 'foo-id')
        link_entry = inventory.make_entry('symlink', 'link', 'TREE_ROOT',
                                          'link-id')
        link_entry.symlink_target = u'link-target'
        inv_delta = [('foo', 'bar/foo2', 'foo-id', foo_entry),
                     ('bar/baz', None, 'baz-id', None),
                     (None, 'link', 'link-id', link_entry),
                    ]
        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=inv_delta,
                                        content_provider=None)
        changes = list(shim._delta_to_iter_changes())
        expected = [('foo-id', ('foo', 'bar/foo2'), False, (True, True),
                     ('TREE_ROOT', 'bar-id'), ('foo', 'foo2'),
                     ('file', 'file'), (False, False)),
                    ('baz-id', ('bar/baz', None), True, (True, False),
                     ('bar-id', None), ('baz', None),
                     ('file', None), (False, None)),
                    ('link-id', (None, 'link'), True, (False, True),
                     (None, 'TREE_ROOT'), (None, 'link'),
                     (None, 'symlink'), (None, False)),
                   ]
        # from pprint import pformat
        # self.assertEqualDiff(pformat(expected), pformat(changes))
        self.assertEqual(expected, changes)

