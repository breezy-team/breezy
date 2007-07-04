# Copyright (C) 2006-2007 by Jelmer Vernooij
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

from bzrlib.errors import UnknownFormatError
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCase, TestCaseWithTransport

from rebase import (marshall_rebase_plan, unmarshall_rebase_plan, 
                    change_revision_parent, generate_simple_plan,
                    generate_transpose_plan) 


class RebasePlanReadWriterTests(TestCase):
    def test_simple_marshall_rebase_plan(self):
        self.assertEqualDiff(
"""# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
""", marshall_rebase_plan((1, "bla"), 
                          {"oldrev": ("newrev", ["newparent1", "newparent2"])}))

    def test_simple_unmarshall_rebase_plan(self):
        self.assertEquals(((1, "bla"), 
                          {"oldrev": ("newrev", ["newparent1", "newparent2"])}),
                         unmarshall_rebase_plan("""# Bazaar rebase plan 1
1 bla
oldrev newrev newparent1 newparent2
"""))

    def test_unmarshall_rebase_plan_formatunknown(self):
        self.assertRaises(UnknownFormatError,
                         unmarshall_rebase_plan, """# Bazaar rebase plan x
1 bla
oldrev newrev newparent1 newparent2
""")


class ConversionTests(TestCaseWithTransport):
    def test_simple(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello', rev_id="bla")
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bloe")
        wt.set_last_revision("bla")
        b.set_revision_history(["bla"])
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bla2")
        
        newrev = change_revision_parent(wt.branch.repository, "bla2", "bla4", 
                                        ["bloe"])
        self.assertEqual("bla4", newrev)
        self.assertTrue(wt.branch.repository.has_revision(newrev))
        self.assertEqual(["bloe"], wt.branch.repository.revision_parents(newrev))


class PlanCreatorTests(TestCaseWithTransport):
    def test_simple_plan_creator(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello', rev_id="bla")
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bloe")
        wt.set_last_revision("bla")
        b.set_revision_history(["bla"])
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bla2")

        self.assertEquals({'bla2': ('newbla2', ["bloe"])}, 
                generate_simple_plan(b.repository, b.revision_history(), "bla2", "bloe", 
                    lambda y: "new"+y.revision_id))
     
    def test_simple_plan_creator_extra_history(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello', rev_id="bla")
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bloe")
        wt.set_last_revision("bla")
        b.set_revision_history(["bla"])
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bla2")
        file('hello', 'w').write('universe')
        wt.commit(message='change hello again', rev_id="bla3")

        self.assertEquals({'bla2': ('newbla2', ["bloe"]), 'bla3': ('newbla3', ['newbla2'])}, 
                generate_simple_plan(b.repository, b.revision_history(), "bla2", "bloe", 
                    lambda y: "new"+y.revision_id))
 

    def test_generate_transpose_plan(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello', rev_id="bla")
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bloe")
        wt.set_last_revision("bla")
        b.set_revision_history(["bla"])
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bla2")
        file('hello', 'w').write('universe')
        wt.commit(message='change hello again', rev_id="bla3")
        wt.set_last_revision("bla")
        b.set_revision_history(["bla"])
        file('hello', 'w').write('somebar')
        wt.commit(message='change hello yet again', rev_id="blie")
        wt.set_last_revision(NULL_REVISION)
        b.set_revision_history([])
        wt.add('hello')
        wt.commit(message='add hello', rev_id="lala")

        self.assertEquals({
                'bla': ('lala', []),
                'blie': ('newblie', ['lala']),
            },
                generate_transpose_plan(b.repository, b.repository.get_revision_graph("blie"), 
                {"bla": "lala"}, lambda y: "new"+y.revision_id))
        self.assertEquals({
                'bla': ('lala', []),
                'bla2': ('newbla2', ['lala']),
                'bla3': ('newbla3', ['newbla2']),
                'blie': ('newblie', ['lala']),
                'bloe': ('newbloe', ['lala'])},
                generate_transpose_plan(b.repository, b.repository.get_revision_graph(), 
                {"bla": "lala"}, lambda y: "new"+y.revision_id))

