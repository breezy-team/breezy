# Copyright (C) 2008 Canonical Ltd
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from cStringIO import StringIO

from bzrlib import shelf_ui, tests


class ExpectShelver(shelf_ui.Shelver):
    """A variant of Shelver that intercepts console activity, for testing."""

    def __init__(self, tree, target_tree):
        shelf_ui.Shelver.__init__(self, tree, target_tree, None)
        self.expected = []
        self.diff_writer = StringIO()

    def expect(self, prompt, response):
        self.expected.append((prompt, response))

    def prompt(self, message):
        try:
            prompt, response = self.expected.pop(0)
        except IndexError:
            raise AssertionError('Unexpected prompt: %s' % message)
        if prompt != message:
            raise AssertionError('Wrong prompt: %s' % message)
        return response


LINES_AJ = 'a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n'


LINES_ZY = 'z\nb\nc\nd\ne\nf\ng\nh\ni\ny\n'


LINES_AY = 'a\nb\nc\nd\ne\nf\ng\nh\ni\ny\n'


class TestShelver(tests.TestCaseWithTransport):

    def create_shelvable_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/foo', LINES_AJ)])
        tree.add('foo', 'foo-id')
        tree.commit('added foo')
        self.build_tree_contents([('tree/foo', LINES_ZY)])
        return tree

    def test_unexpected_prompt_failure(self):
        tree = self.create_shelvable_tree()
        shelver = ExpectShelver(tree, tree.basis_tree())
        e = self.assertRaises(AssertionError, shelver.run)
        self.assertEqual('Unexpected prompt: Shelve? [yNfq]', str(e))

    def test_wrong_prompt_failure(self):
        tree = self.create_shelvable_tree()
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('foo', 'y')
        e = self.assertRaises(AssertionError, shelver.run)
        self.assertEqual('Wrong prompt: Shelve? [yNfq]', str(e))

    def test_shelve_not_diff(self):
        tree = self.create_shelvable_tree()
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq]', 'n')
        shelver.expect('Shelve? [yNfq]', 'n')
        # No final shelving prompt because no changes were selected
        shelver.run()
        self.assertFileEqual(LINES_ZY, 'tree/foo')

    def test_shelve_diff_no(self):
        tree = self.create_shelvable_tree()
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq]', 'y')
        shelver.expect('Shelve? [yNfq]', 'y')
        shelver.expect('Shelve 2 change(s)? [yNfq]', 'n')
        shelver.run()
        self.assertFileEqual(LINES_ZY, 'tree/foo')

    def test_shelve_diff(self):
        tree = self.create_shelvable_tree()
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq]', 'y')
        shelver.expect('Shelve? [yNfq]', 'y')
        shelver.expect('Shelve 2 change(s)? [yNfq]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_one_diff(self):
        tree = self.create_shelvable_tree()
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq]', 'y')
        shelver.expect('Shelve? [yNfq]', 'n')
        shelver.expect('Shelve 1 change(s)? [yNfq]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AY, 'tree/foo')

    def test_shelve_rename(self):
        tree = self.create_shelvable_tree()
        tree.revert()
        tree.rename_one('foo', 'bar')
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve renaming foo => bar? [yNfq]', 'y')
        shelver.expect('Shelve 1 change(s)? [yNfq]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')
