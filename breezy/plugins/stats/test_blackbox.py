"""Blackbox tests for the stats plugin."""

from ...tests import TestCaseWithTransport


class TestBlackbox(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        wt = self.make_branch_and_tree(".")
        self.build_tree_contents([("foo.c", "#include <stdio.h>\n")])
        wt.add("foo.c")
        wt.commit(message="1", committer="Fero <fero@example.com>", rev_id=b"1")
        wt.commit(message="2", committer="Fero <fero@example.com>", rev_id=b"2")
        wt.commit(message="3", committer="Jano <jano@example.com>", rev_id=b"3")
        wt.commit(
            message="4",
            committer="Jano <jano@example.com>",
            authors=["Vinco <vinco@example.com>"],
            rev_id=b"4",
        )
        wt.commit(message="5", committer="Ferko <fero@example.com>", rev_id=b"5")

    def test_stats(self):
        (out, _err) = self.run_bzr("stats")
        self.assertEqual(
            out,
            """\
   3 Fero <fero@example.com>
     Other names:
        2 Fero
        1 Ferko
   1 Vinco <vinco@example.com>
   1 Jano <jano@example.com>
""",
        )

    def test_credits(self):
        (out, _err) = self.run_bzr("credits")
        self.assertEqual(
            out,
            """\
Code:
Fero <fero@example.com>

""",
        )
