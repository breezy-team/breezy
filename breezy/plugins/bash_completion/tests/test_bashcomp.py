# Copyright (C) 2010 by Canonical Ltd
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

import os
import subprocess
import sys

import breezy
from breezy import commands, osutils, tests
from breezy.plugins.bash_completion.bashcomp import *
from breezy.tests import features


class BashCompletionMixin:
    """Component for testing execution of a bash completion script."""

    _test_needs_features = [features.bash_feature]
    script = None

    def complete(self, words, cword=-1):
        """Perform a bash completion.

        :param words: a list of words representing the current command.
        :param cword: the current word to complete, defaults to the last one.
        """
        if self.script is None:
            self.script = self.get_script()
        env = dict(os.environ)
        env["PYTHONPATH"] = ":".join(sys.path)
        proc = subprocess.Popen(
            [features.bash_feature.path, "--noprofile"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        if cword < 0:
            cword = len(words) + cword
        encoding = osutils.get_user_encoding()
        input = b"%s\n" % self.script.encode(encoding)
        input += b"COMP_WORDS=( %s )\n" % b" ".join(
            [b"'" + w.replace("'", "'\\''").encode(encoding) + b"'" for w in words]
        )
        input += b"COMP_CWORD=%d\n" % cword
        input += b"%s\n" % getattr(self, "script_name", "_brz").encode(encoding)
        input += b"echo ${#COMPREPLY[*]}\n"
        input += b"IFS=$'\\n'\n"
        input += b'echo "${COMPREPLY[*]}"\n'
        (out, err) = proc.communicate(input)
        errlines = [
            line for line in err.splitlines() if not line.startswith(b"brz: warning: ")
        ]
        if errlines != []:
            raise AssertionError("Unexpected error message:\n{}".format(err))
        self.assertEqual(b"", b"".join(errlines), "No messages to standard error")
        # import sys
        # print >>sys.stdout, '---\n%s\n---\n%s\n---\n' % (input, out)
        lines = out.split(b"\n")
        nlines = int(lines[0])
        del lines[0]
        self.assertEqual(b"", lines[-1], "Newline at end")
        del lines[-1]
        if nlines == 0 and len(lines) == 1 and lines[0] == b"":
            del lines[0]
        self.assertEqual(nlines, len(lines), "No newlines in generated words")
        self.completion_result = {l.decode(encoding) for l in lines}
        return self.completion_result

    def assertCompletionEquals(self, *words):
        self.assertEqual(set(words), self.completion_result)

    def assertCompletionContains(self, *words):
        missing = set(words) - self.completion_result
        if missing:
            raise AssertionError(
                "Completion should contain {!r} but it has {!r}".format(
                    missing, self.completion_result
                )
            )

    def assertCompletionOmits(self, *words):
        surplus = set(words) & self.completion_result
        if surplus:
            raise AssertionError(
                "Completion should omit {!r} but it has {!r}".format(
                    surplus, self.completion_result
                )
            )

    def get_script(self):
        commands.install_bzr_command_hooks()
        dc = DataCollector()
        data = dc.collect()
        cg = BashCodeGen(data)
        res = cg.function()
        return res


class TestBashCompletion(tests.TestCase, BashCompletionMixin):
    """Test bash completions that don't execute brz."""

    def test_simple_scipt(self):
        """Ensure that the test harness works as expected."""
        self.script = """
_brz() {
    COMPREPLY=()
    # add all words in reverse order, with some markup around them
    for ((i = ${#COMP_WORDS[@]}; i > 0; --i)); do
        COMPREPLY+=( "-${COMP_WORDS[i-1]}+" )
    done
    # and append the current word
    COMPREPLY+=( "+${COMP_WORDS[COMP_CWORD]}-" )
}
"""
        self.complete(["foo", '"bar', "'baz"], cword=1)
        self.assertCompletionEquals("-'baz+", '-"bar+', "-foo+", '+"bar-')

    def test_cmd_ini(self):
        self.complete(["brz", "ini"])
        self.assertCompletionContains(
            "init", "init-shared-repo", "init-shared-repository"
        )
        self.assertCompletionOmits("commit")

    def test_init_opts(self):
        self.complete(["brz", "init", "-"])
        self.assertCompletionContains("-h", "--format=2a")

    def test_global_opts(self):
        self.complete(["brz", "-", "init"], cword=1)
        self.assertCompletionContains("--no-plugins", "--builtin")

    def test_commit_dashm(self):
        self.complete(["brz", "commit", "-m"])
        self.assertCompletionEquals("-m")

    def test_status_negated(self):
        self.complete(["brz", "status", "--n"])
        self.assertCompletionContains("--no-versioned", "--no-verbose")

    def test_init_format_any(self):
        self.complete(["brz", "init", "--format", "=", "directory"], cword=3)
        self.assertCompletionContains("1.9", "2a")

    def test_init_format_2(self):
        self.complete(["brz", "init", "--format", "=", "2", "directory"], cword=4)
        self.assertCompletionContains("2a")
        self.assertCompletionOmits("1.9")


class TestBashCompletionInvoking(tests.TestCaseWithTransport, BashCompletionMixin):
    """Test bash completions that might execute brz.

    Only the syntax ``$(brz ...`` is supported so far. The brz command
    will be replaced by the brz instance running this selftest.
    """

    def setUp(self):
        super().setUp()
        if sys.platform == "win32":
            raise tests.KnownFailure("see bug #709104, completion is broken on windows")

    def get_script(self):
        s = super().get_script()
        s = s.replace("$(brz ", "$({} ".format(" ".join(self.get_brz_command())))
        s = s.replace("2>/dev/null", "")
        return s

    def test_revspec_tag_all(self):
        self.requireFeature(features.sed_feature)
        wt = self.make_branch_and_tree(".")
        wt.branch.tags.set_tag("tag1", b"null:")
        wt.branch.tags.set_tag("tag2", b"null:")
        wt.branch.tags.set_tag("3tag", b"null:")
        self.complete(["brz", "log", "-r", "tag", ":"])
        self.assertCompletionEquals("tag1", "tag2", "3tag")

    def test_revspec_tag_prefix(self):
        self.requireFeature(features.sed_feature)
        wt = self.make_branch_and_tree(".")
        wt.branch.tags.set_tag("tag1", b"null:")
        wt.branch.tags.set_tag("tag2", b"null:")
        wt.branch.tags.set_tag("3tag", b"null:")
        self.complete(["brz", "log", "-r", "tag", ":", "t"])
        self.assertCompletionEquals("tag1", "tag2")

    def test_revspec_tag_spaces(self):
        self.requireFeature(features.sed_feature)
        wt = self.make_branch_and_tree(".")
        wt.branch.tags.set_tag("tag with spaces", b"null:")
        self.complete(["brz", "log", "-r", "tag", ":", "t"])
        self.assertCompletionEquals(r"tag\ with\ spaces")
        self.complete(["brz", "log", "-r", '"tag:t'])
        self.assertCompletionEquals("tag:tag with spaces")
        self.complete(["brz", "log", "-r", "'tag:t"])
        self.assertCompletionEquals("tag:tag with spaces")

    def test_revspec_tag_endrange(self):
        self.requireFeature(features.sed_feature)
        wt = self.make_branch_and_tree(".")
        wt.branch.tags.set_tag("tag1", b"null:")
        wt.branch.tags.set_tag("tag2", b"null:")
        self.complete(["brz", "log", "-r", "3..tag", ":", "t"])
        self.assertCompletionEquals("tag1", "tag2")
        self.complete(["brz", "log", "-r", '"3..tag:t'])
        self.assertCompletionEquals("3..tag:tag1", "3..tag:tag2")
        self.complete(["brz", "log", "-r", "'3..tag:t"])
        self.assertCompletionEquals("3..tag:tag1", "3..tag:tag2")


class TestBashCodeGen(tests.TestCase):
    def test_command_names(self):
        data = CompletionData()
        bar = CommandData("bar")
        bar.aliases.append("baz")
        data.commands.append(bar)
        data.commands.append(CommandData("foo"))
        cg = BashCodeGen(data)
        self.assertEqual("bar baz foo", cg.command_names())

    def test_debug_output(self):
        data = CompletionData()
        self.assertEqual("", BashCodeGen(data, debug=False).debug_output())
        self.assertTrue(BashCodeGen(data, debug=True).debug_output())

    def test_brz_version(self):
        data = CompletionData()
        cg = BashCodeGen(data)
        self.assertEqual("{}.".format(breezy.version_string), cg.brz_version())
        data.plugins["foo"] = PluginData("foo", "1.0")
        data.plugins["bar"] = PluginData("bar", "2.0")
        cg = BashCodeGen(data)
        self.assertEqual(
            """\
{} and the following plugins:
# bar 2.0
# foo 1.0""".format(breezy.version_string),
            cg.brz_version(),
        )

    def test_global_options(self):
        data = CompletionData()
        data.global_options.add("--foo")
        data.global_options.add("--bar")
        cg = BashCodeGen(data)
        self.assertEqual("--bar --foo", cg.global_options())

    def test_command_cases(self):
        data = CompletionData()
        bar = CommandData("bar")
        bar.aliases.append("baz")
        bar.options.append(OptionData("--opt"))
        data.commands.append(bar)
        data.commands.append(CommandData("foo"))
        cg = BashCodeGen(data)
        self.assertEqualDiff(
            """\
\tbar|baz)
\t\tcmdOpts=( --opt )
\t\t;;
\tfoo)
\t\tcmdOpts=(  )
\t\t;;
""",
            cg.command_cases(),
        )

    def test_command_case(self):
        cmd = CommandData("cmd")
        cmd.plugin = PluginData("plugger", "1.0")
        bar = OptionData("--bar")
        bar.registry_keys = ["that", "this"]
        bar.error_messages.append("Some error message")
        cmd.options.append(bar)
        cmd.options.append(OptionData("--foo"))
        data = CompletionData()
        data.commands.append(cmd)
        cg = BashCodeGen(data)
        self.assertEqualDiff(
            """\
\tcmd)
\t\t# plugin "plugger 1.0"
\t\t# Some error message
\t\tcmdOpts=( --bar=that --bar=this --foo )
\t\tcase $curOpt in
\t\t\t--bar) optEnums=( that this ) ;;
\t\tesac
\t\t;;
""",
            cg.command_case(cmd),
        )


class TestDataCollector(tests.TestCase):
    def setUp(self):
        super().setUp()
        commands.install_bzr_command_hooks()

    def test_global_options(self):
        dc = DataCollector()
        dc.global_options()
        self.assertSubset(["--no-plugins", "--builtin"], dc.data.global_options)

    def test_commands(self):
        dc = DataCollector()
        dc.commands()
        self.assertSubset(
            ["init", "init-shared-repo", "init-shared-repository"],
            dc.data.all_command_aliases(),
        )

    def test_commands_from_plugins(self):
        dc = DataCollector()
        dc.commands()
        self.assertSubset(["bash-completion"], dc.data.all_command_aliases())

    def test_commit_dashm(self):
        dc = DataCollector()
        cmd = dc.command("commit")
        self.assertSubset(["-m"], [str(o) for o in cmd.options])

    def test_status_negated(self):
        dc = DataCollector()
        cmd = dc.command("status")
        self.assertSubset(
            ["--no-versioned", "--no-verbose"], [str(o) for o in cmd.options]
        )

    def test_init_format(self):
        dc = DataCollector()
        cmd = dc.command("init")
        for opt in cmd.options:
            if opt.name == "--format":
                self.assertSubset(["2a"], opt.registry_keys)
                return
        raise AssertionError("Option --format not found")


class BlackboxTests(tests.TestCaseWithMemoryTransport):
    def test_bash_completion(self):
        self.run_bzr("bash-completion", encoding="utf-8")
