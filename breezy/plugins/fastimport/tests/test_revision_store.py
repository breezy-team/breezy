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

from .... import (
    branch,
    errors,
    osutils,
    tests,
    )
from ....bzr import (
    inventory,
    )
from .. import (
    revision_store,
    )
from . import (
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
        basis_inv = inventory.Inventory(b'TREE_ROOT')
        self.invAddEntry(basis_inv, 'foo', b'foo-id')
        self.invAddEntry(basis_inv, 'bar/', b'bar-id')
        self.invAddEntry(basis_inv, 'bar/baz', b'baz-id')
        return basis_inv

    def test_id2path_no_delta(self):
        basis_inv = self.make_trivial_basis_inv()
        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=[], content_provider=None)
        self.assertEqual('', shim.id2path(b'TREE_ROOT'))
        self.assertEqual('foo', shim.id2path(b'foo-id'))
        self.assertEqual('bar', shim.id2path(b'bar-id'))
        self.assertEqual('bar/baz', shim.id2path(b'baz-id'))
        self.assertRaises(errors.NoSuchId, shim.id2path, b'qux-id')

    def test_id2path_with_delta(self):
        basis_inv = self.make_trivial_basis_inv()
        foo_entry = inventory.make_entry(
            'file', 'foo2', b'TREE_ROOT', b'foo-id')
        inv_delta = [('foo', 'foo2', b'foo-id', foo_entry),
                     ('bar/baz', None, b'baz-id', None),
                     ]

        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=inv_delta,
                                        content_provider=None)
        self.assertEqual('', shim.id2path(b'TREE_ROOT'))
        self.assertEqual('foo2', shim.id2path(b'foo-id'))
        self.assertEqual('bar', shim.id2path(b'bar-id'))
        self.assertRaises(errors.NoSuchId, shim.id2path, b'baz-id')

    def test_path2id(self):
        basis_inv = self.make_trivial_basis_inv()
        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=[], content_provider=None)
        self.assertEqual(b'TREE_ROOT', shim.path2id(''))
        self.assertEqual(b'bar-id', shim.path2id('bar'))

    def test_get_file_with_stat_content_in_stream(self):
        basis_inv = self.make_trivial_basis_inv()

        def content_provider(file_id):
            return b'content of\n' + file_id + b'\n'

        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=[],
                                        content_provider=content_provider)
        f_obj, stat_val = shim.get_file_with_stat('bar/baz')
        self.assertIs(None, stat_val)
        self.assertEqualDiff(b'content of\nbaz-id\n', f_obj.read())

    # TODO: Test when the content isn't in the stream, and we fall back to the
    #       repository that was passed in

    def test_get_symlink_target(self):
        basis_inv = self.make_trivial_basis_inv()
        ie = inventory.make_entry('symlink', 'link', b'TREE_ROOT', b'link-id')
        ie.symlink_target = u'link-target'
        basis_inv.add(ie)
        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=[], content_provider=None)
        self.assertEqual(u'link-target',
                         shim.get_symlink_target('link'))

    def test_get_symlink_target_from_delta(self):
        basis_inv = self.make_trivial_basis_inv()
        ie = inventory.make_entry('symlink', 'link', b'TREE_ROOT', b'link-id')
        ie.symlink_target = u'link-target'
        inv_delta = [(None, 'link', b'link-id', ie)]
        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=inv_delta,
                                        content_provider=None)
        self.assertEqual(u'link-target',
                         shim.get_symlink_target('link'))

    def test__delta_to_iter_changes(self):
        basis_inv = self.make_trivial_basis_inv()
        foo_entry = inventory.make_entry('file', 'foo2', b'bar-id', b'foo-id')
        link_entry = inventory.make_entry('symlink', 'link', b'TREE_ROOT',
                                          b'link-id')
        link_entry.symlink_target = u'link-target'
        inv_delta = [('foo', 'bar/foo2', b'foo-id', foo_entry),
                     ('bar/baz', None, b'baz-id', None),
                     (None, 'link', b'link-id', link_entry),
                     ]
        shim = revision_store._TreeShim(repo=None, basis_inv=basis_inv,
                                        inv_delta=inv_delta,
                                        content_provider=None)
        changes = list(shim._delta_to_iter_changes())
        expected = [(b'foo-id', ('foo', 'bar/foo2'), False, (True, True),
                     (b'TREE_ROOT', b'bar-id'), ('foo', 'foo2'),
                     ('file', 'file'), (False, False), False),
                    (b'baz-id', ('bar/baz', None), True, (True, False),
                     (b'bar-id', None), ('baz', None),
                     ('file', None), (False, None), False),
                    (b'link-id', (None, 'link'), True, (False, True),
                     (None, b'TREE_ROOT'), (None, 'link'),
                     (None, 'symlink'), (None, False), False),
                    ]
        # from pprint import pformat
        # self.assertEqualDiff(pformat(expected), pformat(changes))
        self.assertEqual(expected, changes)
