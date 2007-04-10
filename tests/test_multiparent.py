from unittest import TestCase

import multiparent

LINES_1 = "a\nb\nc\nd\ne\n".splitlines(True)

class TestMulti(TestCase):

    def test_compare(self):
        diff = multiparent.MultiParent.from_lines(LINES_1)
        self.assertEqual(diff.hunks, [multiparent.NewText(LINES_1)])


class TestNewText(TestCase):

    def test_eq(self):
        self.assertEqual(multiparent.NewText([]), multiparent.NewText([]))
        self.assertFalse(multiparent.NewText(['a']) ==
                         multiparent.NewText(['b']))
        class ThingWithLines(object):
            def __init__(self):
                self.lines = ['a']
        self.assertFalse(multiparent.NewText(['a']) == ThingWithLines())
