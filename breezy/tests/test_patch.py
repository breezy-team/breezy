# Copyright (C) 2006 Canonical Ltd
# Copyright (C) 2008 Aaron Bentley <aaron@aaronbentley.com>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from breezy.tests import TestCaseInTempDir

from ..errors import BinaryFile
from ..patch import diff3, run_patch


class TestPatch(TestCaseInTempDir):
    def test_diff3_binaries(self):
        with open("this", "wb") as f:
            f.write(b"a")
        with open("other", "wb") as f:
            f.write(b"a")
        with open("base", "wb") as f:
            f.write(b"\x00")
        self.assertRaises(BinaryFile, diff3, "unused", "this", "other", "base")


class RunPatchTests(TestCaseInTempDir):
    def test_new_file(self):
        run_patch(
            ".",
            b"""\
 message           | 3 +++
 1 files changed, 14 insertions(+)
 create mode 100644 message

diff --git a/message b/message
new file mode 100644
index 0000000..05ec0b1
--- /dev/null
+++ b/message
@@ -0,0 +1,3 @@
+Update standards version, no changes needed.
+Certainty: certain
+Fixed-Lintian-Tags: out-of-date-standards-version
""".splitlines(True),
            strip=1,
        )
        self.assertFileEqual(
            """\
Update standards version, no changes needed.
Certainty: certain
Fixed-Lintian-Tags: out-of-date-standards-version
""",
            "message",
        )
