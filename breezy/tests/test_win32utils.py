# Copyright (C) 2007-2011, 2016 Canonical Ltd
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

"""Tests for win32utils."""

import os
from typing import List

from .. import osutils, tests, win32utils
from ..win32utils import get_app_path, glob_expand
from . import TestCase, TestCaseInTempDir, TestSkipped, features
from .features import backslashdir_feature

Win32RegistryFeature = features.ModuleAvailableFeature("_winreg")


class TestWin32UtilsGlobExpand(TestCaseInTempDir):
    _test_needs_features: List[features.Feature] = []

    def test_empty_tree(self):
        self.build_tree([])
        self._run_testset(
            [[["a"], ["a"]], [["?"], ["?"]], [["*"], ["*"]], [["a", "a"], ["a", "a"]]]
        )

    def build_ascii_tree(self):
        self.build_tree(
            [
                "a",
                "a1",
                "a2",
                "a11",
                "a.1",
                "b",
                "b1",
                "b2",
                "b3",
                "c/",
                "c/c1",
                "c/c2",
                "d/",
                "d/d1",
                "d/d2",
                "d/e/",
                "d/e/e1",
            ]
        )

    def build_unicode_tree(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self.build_tree(["\u1234", "\u1234\u1234", "\u1235/", "\u1235/\u1235"])

    def test_tree_ascii(self):
        """Checks the glob expansion and path separation char
        normalization
        """
        self.build_ascii_tree()
        self._run_testset(
            [
                # no wildcards
                [["a"], ["a"]],
                [["a", "a"], ["a", "a"]],
                [["d"], ["d"]],
                [["d/"], ["d/"]],
                # wildcards
                [["a*"], ["a", "a1", "a2", "a11", "a.1"]],
                [["?"], ["a", "b", "c", "d"]],
                [["a?"], ["a1", "a2"]],
                [["a??"], ["a11", "a.1"]],
                [["b[1-2]"], ["b1", "b2"]],
                [["d/*"], ["d/d1", "d/d2", "d/e"]],
                [["?/*"], ["c/c1", "c/c2", "d/d1", "d/d2", "d/e"]],
                [["*/*"], ["c/c1", "c/c2", "d/d1", "d/d2", "d/e"]],
                [["*/"], ["c/", "d/"]],
            ]
        )

    def test_backslash_globbing(self):
        self.requireFeature(backslashdir_feature)
        self.build_ascii_tree()
        self._run_testset(
            [
                [["d\\"], ["d/"]],
                [["d\\*"], ["d/d1", "d/d2", "d/e"]],
                [["?\\*"], ["c/c1", "c/c2", "d/d1", "d/d2", "d/e"]],
                [["*\\*"], ["c/c1", "c/c2", "d/d1", "d/d2", "d/e"]],
                [["*\\"], ["c/", "d/"]],
            ]
        )

    def test_case_insensitive_globbing(self):
        if os.path.normcase("AbC") == "AbC":
            self.skipTest("Test requires case insensitive globbing function")
        self.build_ascii_tree()
        self._run_testset(
            [
                [["A"], ["A"]],
                [["A?"], ["a1", "a2"]],
            ]
        )

    def test_tree_unicode(self):
        """Checks behaviour with non-ascii filenames"""
        self.build_unicode_tree()
        self._run_testset(
            [
                # no wildcards
                [["\u1234"], ["\u1234"]],
                [["\u1235"], ["\u1235"]],
                [["\u1235/"], ["\u1235/"]],
                [["\u1235/\u1235"], ["\u1235/\u1235"]],
                # wildcards
                [["?"], ["\u1234", "\u1235"]],
                [["*"], ["\u1234", "\u1234\u1234", "\u1235"]],
                [["\u1234*"], ["\u1234", "\u1234\u1234"]],
                [["\u1235/?"], ["\u1235/\u1235"]],
                [["\u1235/*"], ["\u1235/\u1235"]],
                [["?/"], ["\u1235/"]],
                [["*/"], ["\u1235/"]],
                [["?/?"], ["\u1235/\u1235"]],
                [["*/*"], ["\u1235/\u1235"]],
            ]
        )

    def test_unicode_backslashes(self):
        self.requireFeature(backslashdir_feature)
        self.build_unicode_tree()
        self._run_testset(
            [
                # no wildcards
                [["\u1235\\"], ["\u1235/"]],
                [["\u1235\\\u1235"], ["\u1235/\u1235"]],
                [["\u1235\\?"], ["\u1235/\u1235"]],
                [["\u1235\\*"], ["\u1235/\u1235"]],
                [["?\\"], ["\u1235/"]],
                [["*\\"], ["\u1235/"]],
                [["?\\?"], ["\u1235/\u1235"]],
                [["*\\*"], ["\u1235/\u1235"]],
            ]
        )

    def _run_testset(self, testset):
        for pattern, expected in testset:
            result = glob_expand(pattern)
            expected.sort()
            result.sort()
            self.assertEqual(expected, result, "pattern %s" % pattern)


class TestAppPaths(TestCase):
    _test_needs_features = [Win32RegistryFeature]

    def test_iexplore(self):
        # typical windows users should have IE installed
        for a in ("iexplore", "iexplore.exe"):
            p = get_app_path(a)
            d, b = os.path.split(p)
            self.assertEqual("iexplore.exe", b.lower())
            self.assertNotEqual("", d)

    def test_wordpad(self):
        # typical windows users should have wordpad in the system
        # but there is problem: its path has the format REG_EXPAND_SZ
        # so naive attempt to get the path is not working
        self.requireFeature(Win32ApiFeature)
        for a in ("wordpad", "wordpad.exe"):
            p = get_app_path(a)
            d, b = os.path.split(p)
            self.assertEqual("wordpad.exe", b.lower())
            self.assertNotEqual("", d)

    def test_not_existing(self):
        p = get_app_path("not-existing")
        self.assertEqual("not-existing", p)


class TestLocations(TestCase):
    _test_needs_features = [features.win32_feature]

    def assertPathsEqual(self, p1, p2):
        # TODO: The env var values in particular might return the "short"
        # version (ie, "C:\DOCUME~1\...").  Its even possible the returned
        # values will differ only by case - handle these situations as we
        # come across them.
        self.assertEqual(p1, p2)

    def test_appdata_not_using_environment(self):
        # Test that we aren't falling back to the environment
        first = win32utils.get_appdata_location()
        self.overrideEnv("APPDATA", None)
        self.assertPathsEqual(first, win32utils.get_appdata_location())

    def test_appdata_matches_environment(self):
        # Typically the APPDATA environment variable will match
        # get_appdata_location
        # XXX - See bug 262874, which asserts the correct encoding is 'mbcs',
        encoding = osutils.get_user_encoding()
        env_val = os.environ.get("APPDATA", None)
        if not env_val:
            raise TestSkipped("No APPDATA environment variable exists")
        self.assertPathsEqual(
            win32utils.get_appdata_location(), env_val.decode(encoding)
        )

    def test_local_appdata_not_using_environment(self):
        # Test that we aren't falling back to the environment
        first = win32utils.get_local_appdata_location()
        self.overrideEnv("LOCALAPPDATA", None)
        self.assertPathsEqual(first, win32utils.get_local_appdata_location())

    def test_local_appdata_matches_environment(self):
        # LOCALAPPDATA typically only exists on Vista, so we only attempt to
        # compare when it exists.
        lad = win32utils.get_local_appdata_location()
        env = os.environ.get("LOCALAPPDATA")
        if env:
            # XXX - See bug 262874, which asserts the correct encoding is
            # 'mbcs'
            encoding = osutils.get_user_encoding()
            self.assertPathsEqual(lad, env.decode(encoding))


class TestSetHidden(TestCaseInTempDir):
    _test_needs_features = [features.win32_feature]

    def test_unicode_dir(self):
        # we should handle unicode paths without errors
        self.requireFeature(features.UnicodeFilenameFeature)
        os.mkdir("\u1234")
        win32utils.set_file_attr_hidden("\u1234")

    def test_dot_bzr_in_unicode_dir(self):
        # we should not raise traceback if we try to set hidden attribute
        # on .bzr directory below unicode path
        self.requireFeature(features.UnicodeFilenameFeature)
        os.makedirs("\u1234\\.bzr")
        path = osutils.abspath("\u1234\\.bzr")
        win32utils.set_file_attr_hidden(path)


class Test_CommandLineToArgv(tests.TestCaseInTempDir):
    def assertCommandLine(self, expected, line, argv=None, single_quotes_allowed=False):
        # Strictly speaking we should respect parameter order versus glob
        # expansions, but it's not really worth the effort here
        if argv is None:
            argv = [line]
        argv = win32utils._command_line_to_argv(
            line, argv, single_quotes_allowed=single_quotes_allowed
        )
        self.assertEqual(expected, sorted(argv))

    def test_glob_paths(self):
        self.build_tree(["a/", "a/b.c", "a/c.c", "a/c.h"])
        self.assertCommandLine(["a/b.c", "a/c.c"], "a/*.c")
        self.build_tree(["b/", "b/b.c", "b/d.c", "b/d.h"])
        self.assertCommandLine(["a/b.c", "b/b.c"], "*/b.c")
        self.assertCommandLine(["a/b.c", "a/c.c", "b/b.c", "b/d.c"], "*/*.c")
        # Bash style, just pass through the argument if nothing matches
        self.assertCommandLine(["*/*.qqq"], "*/*.qqq")

    def test_quoted_globs(self):
        self.build_tree(["a/", "a/b.c", "a/c.c", "a/c.h"])
        self.assertCommandLine(["a/*.c"], '"a/*.c"')
        self.assertCommandLine(["'a/*.c'"], "'a/*.c'")
        self.assertCommandLine(["a/*.c"], "'a/*.c'", single_quotes_allowed=True)

    def test_slashes_changed(self):
        # Quoting doesn't change the supplied args
        self.assertCommandLine(["a\\*.c"], '"a\\*.c"')
        self.assertCommandLine(["a\\*.c"], "'a\\*.c'", single_quotes_allowed=True)
        # Expands the glob, but nothing matches, swaps slashes
        self.assertCommandLine(["a/*.c"], "a\\*.c")
        self.assertCommandLine(["a/?.c"], "a\\?.c")
        # No glob, doesn't touch slashes
        self.assertCommandLine(["a\\foo.c"], "a\\foo.c")

    def test_single_quote_support(self):
        self.assertCommandLine(
            ["add", "let's-do-it.txt"],
            "add let's-do-it.txt",
            ["add", "let's-do-it.txt"],
        )
        self.expectFailure(
            "Using single quotes breaks trimming from argv",
            self.assertCommandLine,
            ["add", "lets do it.txt"],
            "add 'lets do it.txt'",
            ["add", "'lets", "do", "it.txt'"],
            single_quotes_allowed=True,
        )

    def test_case_insensitive_globs(self):
        if os.path.normcase("AbC") == "AbC":
            self.skipTest("Test requires case insensitive globbing function")
        self.build_tree(["a/", "a/b.c", "a/c.c", "a/c.h"])
        self.assertCommandLine(["A/b.c"], "A/B*")

    def test_backslashes(self):
        self.requireFeature(backslashdir_feature)
        self.build_tree(["a/", "a/b.c", "a/c.c", "a/c.h"])
        self.assertCommandLine(["a/b.c"], "a\\b*")

    def test_with_pdb(self):
        """Check stripping Python arguments before bzr script per lp:587868"""
        self.assertCommandLine(["rocks"], "-m pdb rocks", ["rocks"])
        self.build_tree(["d/", "d/f1", "d/f2"])
        self.assertCommandLine(["rm", "x*"], "-m pdb rm x*", ["rm", "x*"])
        self.assertCommandLine(
            ["add", "d/f1", "d/f2"], "-m pdb add d/*", ["add", "d/*"]
        )
