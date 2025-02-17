# Copyright (C) 2010 Canonical Ltd
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

"""Test the command implementations."""

import gzip
import os
import re
import tempfile

from .... import tests
from ....tests import features
from ....tests.blackbox import ExternalBase
from ..cmds import _get_source_stream
from . import FastimportFeature


class TestSourceStream(tests.TestCase):
    _test_needs_features = [FastimportFeature]

    def test_get_source_stream_stdin(self):
        # - returns standard in
        self.assertIsNot(None, _get_source_stream("-"))

    def test_get_source_gz(self):
        # files ending in .gz are automatically decompressed.
        fd, filename = tempfile.mkstemp(suffix=".gz")
        with gzip.GzipFile(fileobj=os.fdopen(fd, "wb"), mode="wb") as f:
            f.write(b"bla")
        stream = _get_source_stream(filename)
        self.assertIsNot("bla", stream.read())

    def test_get_source_file(self):
        # other files are opened as regular files.
        fd, filename = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(b"bla")
        stream = _get_source_stream(filename)
        self.assertIsNot(b"bla", stream.read())


fast_export_baseline_data1 = """reset refs/heads/master
commit refs/heads/master
mark :1
committer
data 15
add c, remove b
M 644 inline a
data 13
test 1
test 3
M 644 inline c
data 6
test 4
commit refs/heads/master
mark :2
committer
data 14
modify a again
from :1
M 644 inline a
data 20
test 1
test 3
test 5
commit refs/heads/master
mark :3
committer
data 5
add d
from :2
M 644 inline d
data 6
test 6
"""


fast_export_baseline_data2 = """reset refs/heads/master
commit refs/heads/master
mark :1
committer
data 15
add c, remove b
M 644 inline c
data 6
test 4
M 644 inline a
data 13
test 1
test 3
commit refs/heads/master
mark :2
committer
data 14
modify a again
from :1
M 644 inline a
data 20
test 1
test 3
test 5
commit refs/heads/master
mark :3
committer
data 5
add d
from :2
M 644 inline d
data 6
test 6
"""


class TestFastExport(ExternalBase):
    _test_needs_features = [FastimportFeature]

    def test_empty(self):
        self.make_branch_and_tree("br")
        self.assertEqual("", self.run_bzr("fast-export br")[0])

    def test_pointless(self):
        tree = self.make_branch_and_tree("br")
        tree.commit("pointless")
        data = self.run_bzr("fast-export br")[0]
        self.assertTrue(
            data.startswith(
                "reset refs/heads/master\ncommit refs/heads/master\nmark :1\ncommitter"
            ),
            data,
        )

    def test_file(self):
        tree = self.make_branch_and_tree("br")
        tree.commit("pointless")
        data = self.run_bzr("fast-export br br.fi")[0]
        self.assertEqual("", data)
        self.assertPathExists("br.fi")

    def test_symlink(self):
        tree = self.make_branch_and_tree("br")
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        os.symlink("symlink-target", "br/symlink")
        tree.add("symlink")
        tree.commit("add a symlink")
        data = self.run_bzr("fast-export br br.fi")[0]
        self.assertEqual("", data)
        self.assertPathExists("br.fi")

    def test_tag_rewriting(self):
        tree = self.make_branch_and_tree("br")
        tree.commit("pointless")
        self.assertTrue(tree.branch.supports_tags())
        rev_id = tree.branch.dotted_revno_to_revision_id((1,))
        tree.branch.tags.set_tag("goodTag", rev_id)
        tree.branch.tags.set_tag("bad Tag", rev_id)

        # first check --no-rewrite-tag-names
        data = self.run_bzr("fast-export --plain --no-rewrite-tag-names br")[0]
        self.assertNotEqual(-1, data.find("reset refs/tags/goodTag"))
        self.assertEqual(data.find("reset refs/tags/"), data.rfind("reset refs/tags/"))

        # and now with --rewrite-tag-names
        data = self.run_bzr("fast-export --plain --rewrite-tag-names br")[0]
        self.assertNotEqual(-1, data.find("reset refs/tags/goodTag"))
        # "bad Tag" should be exported as bad_Tag
        self.assertNotEqual(-1, data.find("reset refs/tags/bad_Tag"))

    def test_no_tags(self):
        tree = self.make_branch_and_tree("br")
        tree.commit("pointless")
        self.assertTrue(tree.branch.supports_tags())
        rev_id = tree.branch.dotted_revno_to_revision_id((1,))
        tree.branch.tags.set_tag("someTag", rev_id)

        data = self.run_bzr("fast-export --plain --no-tags br")[0]
        self.assertEqual(-1, data.find("reset refs/tags/someTag"))

    def test_baseline_option(self):
        tree = self.make_branch_and_tree("bl")

        # Revision 1
        with open("bl/a", "w") as f:
            f.write("test 1")
        tree.add("a")
        tree.commit(message="add a")

        # Revision 2
        with open("bl/b", "w") as f:
            f.write("test 2")
        with open("bl/a", "a") as f:
            f.write("\ntest 3")
        tree.add("b")
        tree.commit(message="add b, modify a")

        # Revision 3
        with open("bl/c", "w") as f:
            f.write("test 4")
        tree.add("c")
        tree.remove("b")
        tree.commit(message="add c, remove b")

        # Revision 4
        with open("bl/a", "a") as f:
            f.write("\ntest 5")
        tree.commit(message="modify a again")

        # Revision 5
        with open("bl/d", "w") as f:
            f.write("test 6")
        tree.add("d")
        tree.commit(message="add d")

        # This exports the baseline state at Revision 3,
        # followed by the deltas for 4 and 5
        data = self.run_bzr("fast-export --baseline -r 3.. bl")[0]
        data = re.sub("committer.*", "committer", data)
        self.assertIn(data, (fast_export_baseline_data1, fast_export_baseline_data2))

        # Also confirm that --baseline with no args is identical to full export
        data1 = self.run_bzr("fast-export --baseline bl")[0]
        data2 = self.run_bzr("fast-export bl")[0]
        self.assertEqual(data1, data2)


simple_fast_import_stream = b"""commit refs/heads/master
mark :1
committer Jelmer Vernooij <jelmer@samba.org> 1299718135 +0100
data 7
initial

"""


class TestFastImport(ExternalBase):
    _test_needs_features = [FastimportFeature]

    def test_empty(self):
        self.build_tree_contents([("empty.fi", b"")])
        self.make_branch_and_tree("br")
        self.assertEqual("", self.run_bzr("fast-import empty.fi br")[0])

    def test_file(self):
        tree = self.make_branch_and_tree("br")
        self.build_tree_contents([("file.fi", simple_fast_import_stream)])
        self.run_bzr("fast-import file.fi br")[0]
        self.assertEqual(1, tree.branch.revno())

    def test_missing_bytes(self):
        self.build_tree_contents(
            [
                (
                    "empty.fi",
                    b"""
commit refs/heads/master
mark :1
committer
data 15
""",
                )
            ]
        )
        self.make_branch_and_tree("br")
        self.run_bzr_error(
            [
                "brz: ERROR: 4: Parse error: line 4: Command .*commit.* is missing section .*committer.*\n"
            ],
            "fast-import empty.fi br",
        )
