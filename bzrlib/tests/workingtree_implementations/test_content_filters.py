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

"""Tests for content filtering conformance"""

from bzrlib.filters import ContentFilter
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


def _swapcase(chunks, context=None):
    """A filter that swaps the case of text."""
    result = []
    for chunk in chunks:
        result.append(chunk.swapcase())
    return iter(result)


def _uppercase(chunks, context=None):
    """A filter that converts text to uppercase."""
    result = []
    for chunk in chunks:
        result.append(chunk.upper())
    return iter(result)

def _lowercase(chunks, context=None):
    """A filter that converts text to lowercase."""
    result = []
    for chunk in chunks:
        result.append(chunk.lower())
    return iter(result)


class TestWorkingTreeWithContentFilters(TestCaseWithWorkingTree):

    def create_cf_tree(self, txt_read_filter, txt_write_filter):
        t = self.make_branch_and_tree('t')
        def _content_filter_stack(path=None, file_id=None):
            if path.endswith('.txt'):
                return [ContentFilter(txt_read_filter, txt_write_filter)]
            else:
                return []
        t._content_filter_stack = _content_filter_stack
        t.add(['file1.txt'], ids=['file1-id'], kinds=['file'])
        t.put_file_bytes_non_atomic('file1-id', 'Foo Txt')
        t.add(['file2.bin'], ids=['file2-id'], kinds=['file'])
        t.put_file_bytes_non_atomic('file2-id', 'Foo Bin')
        t.commit('commit raw content')
        return t

    def test_symmetric_content_filtering(self):
        # test handling when read then write gives back the initial content
        t = self.create_cf_tree(txt_read_filter=_swapcase,
            txt_write_filter=_swapcase)
        # Check that the basis tree has the transformed content
        basis = t.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        self.assertEqual('fOO tXT', basis.get_file('file1-id').read())
        self.assertEqual('Foo Bin', basis.get_file('file2-id').read())
        # Check that the working tree has the original content
        t.lock_read()
        self.addCleanup(t.unlock)
        self.assertEqual('Foo Txt', t.get_file('file1-id',
            filtered=False).read())
        self.assertEqual('Foo Bin', t.get_file('file2-id',
            filtered=False).read())

    def test_readonly_content_filtering(self):
        # test handling with a read filter but no write filter
        t = self.create_cf_tree(txt_read_filter=_uppercase,
            txt_write_filter=None)
        # Check that the basis tree has the transformed content
        basis = t.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        self.assertEqual('FOO TXT', basis.get_file('file1-id').read())
        self.assertEqual('Foo Bin', basis.get_file('file2-id').read())
        # We expect the workingtree content to be unchanged (for now at least)
        t.lock_read()
        self.addCleanup(t.unlock)
        self.assertEqual('Foo Txt', t.get_file('file1-id',
            filtered=False).read())
        self.assertEqual('Foo Bin', t.get_file('file2-id',
            filtered=False).read())

    def test_writeonly_content_filtering(self):
        # test handling with a write filter but no read filter
        t = self.create_cf_tree(txt_read_filter=None,
            txt_write_filter=_uppercase)
        # Check that the basis tree has the original content
        bt = t.basis_tree()
        bt.lock_read()
        try:
            self.assertEqual('Foo Txt', bt.get_file('file1-id').read())
            self.assertEqual('Foo Bin', bt.get_file('file2-id').read())
        finally:
            bt.unlock()
        # Check for transformed text content in the working tree
        t.lock_read()
        self.addCleanup(t.unlock)
        self.assertEqual('FOO TXT', t.get_file('file1-id',
            filtered=False).read())
        self.assertEqual('Foo Bin', t.get_file('file2-id',
            filtered=False).read())
