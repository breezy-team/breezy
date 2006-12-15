# Copyright (C) 2006 Canonical Ltd
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

from bzrlib import annotate, tests

def annotation(text):
    return [tuple(l.split(' ', 1)) for l in text.splitlines(True)]

parent_1 = annotation("""\
rev1 a
rev2 b
rev3 c
rev4 d
rev5 e
""")

parent_2 = annotation("""\
rev1 a
rev3 c
rev4 d
rev6 f
rev7 e
rev8 h
""")

expected_2_1 = annotation("""\
rev1 a
blahblah b
rev3 c
rev4 d
rev7 e
""")

# a: in both, same value, kept
# b: in 1, kept
# c: in both, same value, kept
# d: in both, same value, kept
# e: 1 and 2 disagree, so it goes to blahblah
# f: in 2, but not in new, so ignored
# g: not in 1 or 2, so it goes to blahblah
# h: only in parent 2, so 2 gets it
expected_1_2_2 = annotation("""\
rev1 a
rev2 b
rev3 c
rev4 d
blahblah e
blahblah g
rev8 h
""")

new_1 = """\
a
b
c
d
e
""".splitlines(True)

new_2 = """\
a
b
c
d
e
g
h
""".splitlines(True)


class TestAnnotate(tests.TestCase):

    def annotateEqual(self, expected, parents, newlines, revision_id):
        annotate_list = list(annotate.reannotate(parents, newlines,
                             revision_id))
        self.assertEqual(len(expected), len(annotate_list))
        for e, a in zip(expected, annotate_list):
            self.assertEqual(e, a)

    def test_reannotate(self):
        self.annotateEqual(parent_1, [parent_1], new_1, 'blahblah')
        self.annotateEqual(expected_2_1, [parent_2], new_1, 'blahblah')
        self.annotateEqual(expected_1_2_2, [parent_1, parent_2], new_2, 
                           'blahblah')
