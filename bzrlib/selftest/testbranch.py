# (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import os

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.trace import mutter


class TestAppendRevisions(TestCaseInTempDir):
    """Test appending more than one revision"""
    def test_append_revisions(self):
        from bzrlib.branch import Branch
        br = Branch.initialize(".")
        br.append_revision("rev1")
        self.assertEquals(br.revision_history(), ["rev1",])
        br.append_revision("rev2", "rev3")
        self.assertEquals(br.revision_history(), ["rev1", "rev2", "rev3"])



class TestFetch(TestCaseInTempDir):
    def test_fetch_revisions(self):
        """Test fetch-revision operation."""
        from bzrlib.fetch import Fetcher
        os.mkdir('b1')
        os.mkdir('b2')
        b1 = Branch.initialize('b1')
        b2 = Branch.initialize('b2')
        file(os.sep.join(['b1', 'foo']), 'w').write('hello')
        b1.add(['foo'], ['foo-id'])
        b1.commit('lala!', rev_id='revision-1', allow_pointless=False)

        mutter('start fetch')
        f = Fetcher(from_branch=b1, to_branch=b2)
        eq = self.assertEquals
        eq(f.count_copied, 1)
        eq(f.last_revision, 'revision-1')

        rev = b2.get_revision('revision-1')
        tree = b2.revision_tree('revision-1')
        eq(tree.get_file_text('foo-id'), 'hello')


# TODO: rewrite this as a regular unittest, without relying on the displayed output        
#         >>> from bzrlib.commit import commit
#         >>> bzrlib.trace.silent = True
#         >>> br1 = ScratchBranch(files=['foo', 'bar'])
#         >>> br1.add('foo')
#         >>> br1.add('bar')
#         >>> commit(br1, "lala!", rev_id="REVISION-ID-1", verbose=False)
#         >>> br2 = ScratchBranch()
#         >>> br2.update_revisions(br1)
#         Added 2 texts.
#         Added 1 inventories.
#         Added 1 revisions.
#         >>> br2.revision_history()
#         [u'REVISION-ID-1']
#         >>> br2.update_revisions(br1)
#         Added 0 revisions.
#         >>> br1.text_store.total_size() == br2.text_store.total_size()
#         True
