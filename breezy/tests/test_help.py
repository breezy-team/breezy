# Copyright (C) 2007-2012, 2016 Canonical Ltd
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

"""Unit tests for the breezy.help module."""

import re
import textwrap

from .. import (
    builtins,
    commands,
    config,
    errors,
    help,
    help_topics,
    i18n,
    plugin,
    tests,
)
from .test_i18n import ZzzTranslations


class TestErrors(tests.TestCase):
    def test_no_help_topic(self):
        error = help.NoHelpTopic("topic")
        self.assertEqualDiff(
            "No help could be found for 'topic'. "
            "Please use 'brz help topics' to obtain a list of topics.",
            str(error),
        )


class TestCommandHelp(tests.TestCase):
    """Tests for help on commands."""

    def assertCmdHelp(self, expected, cmd):
        self.assertEqualDiff(textwrap.dedent(expected), cmd.get_help_text())

    def test_command_help_includes_see_also(self):
        class cmd_WithSeeAlso(commands.Command):
            __doc__ = """A sample command."""
            _see_also = ["foo", "bar"]

        self.assertCmdHelp(
            """\
Purpose: A sample command.
Usage:   brz WithSeeAlso

Options:
  -h, --help     Show help message.
  -q, --quiet    Only display errors and warnings.
  --usage        Show usage message and options.
  -v, --verbose  Display more information.

See also: bar, foo
""",
            cmd_WithSeeAlso(),
        )

    def test_get_help_text(self):
        """Commands have a get_help_text method which returns their help."""

        class cmd_Demo(commands.Command):
            __doc__ = """A sample command."""

        self.assertCmdHelp(
            """\
Purpose: A sample command.
Usage:   brz Demo

Options:
  -h, --help     Show help message.
  -q, --quiet    Only display errors and warnings.
  --usage        Show usage message and options.
  -v, --verbose  Display more information.

""",
            cmd_Demo(),
        )
        cmd = cmd_Demo()
        helptext = cmd.get_help_text()
        self.assertStartsWith(helptext, "Purpose: A sample command.\nUsage:   brz Demo")
        self.assertEndsWith(helptext, "  -v, --verbose  Display more information.\n\n")

    def test_command_with_additional_see_also(self):
        class cmd_WithSeeAlso(commands.Command):
            __doc__ = """A sample command."""
            _see_also = ["foo", "bar"]

        cmd = cmd_WithSeeAlso()
        helptext = cmd.get_help_text(["gam"])
        self.assertEndsWith(
            helptext,
            "  -h, --help     Show help message.\n"
            "  -q, --quiet    Only display errors and warnings.\n"
            "  --usage        Show usage message and options.\n"
            "  -v, --verbose  Display more information.\n"
            "\n"
            "See also: bar, foo, gam\n",
        )

    def test_command_only_additional_see_also(self):
        class cmd_WithSeeAlso(commands.Command):
            __doc__ = """A sample command."""

        cmd = cmd_WithSeeAlso()
        helptext = cmd.get_help_text(["gam"])
        self.assertEndsWith(
            helptext,
            "  -v, --verbose  Display more information.\n\nSee also: gam\n",
        )

    def test_get_help_topic(self):
        """The help topic for a Command is its name()."""

        class cmd_foo_bar(commands.Command):
            __doc__ = """A sample command."""

        cmd = cmd_foo_bar()
        self.assertEqual(cmd.name(), cmd.get_help_topic())

    def test_formatted_help_text(self):
        """Help text should be plain text by default."""

        class cmd_Demo(commands.Command):
            __doc__ = """A sample command.

            :Examples:
                Example 1::

                    cmd arg1

                Example 2::

                    cmd arg2

                A code block follows.

                ::

                    brz Demo something
            """

        cmd = cmd_Demo()
        helptext = cmd.get_help_text()
        self.assertEqualDiff(
            """\
Purpose: A sample command.
Usage:   brz Demo

Options:
  -h, --help     Show help message.
  -q, --quiet    Only display errors and warnings.
  --usage        Show usage message and options.
  -v, --verbose  Display more information.

Examples:
    Example 1:

        cmd arg1

    Example 2:

        cmd arg2

    A code block follows.

        brz Demo something

""",
            helptext,
        )
        helptext = cmd.get_help_text(plain=False)
        self.assertEqualDiff(
            """\
:Purpose: A sample command.
:Usage:   brz Demo

:Options:
  -h, --help     Show help message.
  -q, --quiet    Only display errors and warnings.
  --usage        Show usage message and options.
  -v, --verbose  Display more information.

:Examples:
    Example 1::

        cmd arg1

    Example 2::

        cmd arg2

    A code block follows.

    ::

        brz Demo something

""",
            helptext,
        )

    def test_concise_help_text(self):
        """Concise help text excludes the descriptive sections."""

        class cmd_Demo(commands.Command):
            __doc__ = """A sample command.

            Blah blah blah.

            :Examples:
                Example 1::

                    cmd arg1
            """

        cmd = cmd_Demo()
        helptext = cmd.get_help_text()
        self.assertEqualDiff(
            """\
Purpose: A sample command.
Usage:   brz Demo

Options:
  -h, --help     Show help message.
  -q, --quiet    Only display errors and warnings.
  --usage        Show usage message and options.
  -v, --verbose  Display more information.

Description:
  Blah blah blah.

Examples:
    Example 1:

        cmd arg1

""",
            helptext,
        )
        helptext = cmd.get_help_text(verbose=False)
        self.assertEqualDiff(
            """\
Purpose: A sample command.
Usage:   brz Demo

Options:
  -h, --help     Show help message.
  -q, --quiet    Only display errors and warnings.
  --usage        Show usage message and options.
  -v, --verbose  Display more information.

See brz help Demo for more details and examples.

""",
            helptext,
        )

    def test_help_custom_section_ordering(self):
        """Custom descriptive sections should remain in the order given."""

        class cmd_Demo(commands.Command):
            __doc__ = """\
A sample command.

Blah blah blah.

:Formats:
  Interesting stuff about formats.

:Examples:
  Example 1::

    cmd arg1

:Tips:
  Clever things to keep in mind.
"""

        cmd = cmd_Demo()
        helptext = cmd.get_help_text()
        self.assertEqualDiff(
            """\
Purpose: A sample command.
Usage:   brz Demo

Options:
  -h, --help     Show help message.
  -q, --quiet    Only display errors and warnings.
  --usage        Show usage message and options.
  -v, --verbose  Display more information.

Description:
  Blah blah blah.

Formats:
  Interesting stuff about formats.

Examples:
  Example 1:

    cmd arg1

Tips:
  Clever things to keep in mind.

""",
            helptext,
        )

    def test_help_text_custom_usage(self):
        """Help text may contain a custom usage section."""

        class cmd_Demo(commands.Command):
            __doc__ = """A sample command.

            :Usage:
                cmd Demo [opts] args

                cmd Demo -h

            Blah blah blah.
            """

        cmd = cmd_Demo()
        helptext = cmd.get_help_text()
        self.assertEqualDiff(
            """\
Purpose: A sample command.
Usage:
    cmd Demo [opts] args

    cmd Demo -h


Options:
  -h, --help     Show help message.
  -q, --quiet    Only display errors and warnings.
  --usage        Show usage message and options.
  -v, --verbose  Display more information.

Description:
  Blah blah blah.

""",
            helptext,
        )


class ZzzTranslationsForDoc(ZzzTranslations):
    _section_pat = re.compile(":\\w+:\\n\\s+")
    _indent_pat = re.compile("\\s+")

    def zzz(self, s):
        m = self._section_pat.match(s)
        if m is None:
            m = self._indent_pat.match(s)
        if m:
            return "{}zz{{{{{}}}}}".format(m.group(0), s[m.end() :])
        return "zz{{{{{}}}}}".format(s)


class TestCommandHelpI18n(tests.TestCase):
    """Tests for help on translated commands."""

    def setUp(self):
        super().setUp()
        self.overrideAttr(i18n, "_translations", ZzzTranslationsForDoc())

    def assertCmdHelp(self, expected, cmd):
        self.assertEqualDiff(textwrap.dedent(expected), cmd.get_help_text())

    def test_command_help_includes_see_also(self):
        class cmd_WithSeeAlso(commands.Command):
            __doc__ = """A sample command."""
            _see_also = ["foo", "bar"]

        self.assertCmdHelp(
            """\
zz{{:Purpose: zz{{A sample command.}}
}}zz{{:Usage:   brz WithSeeAlso
}}
zz{{:Options:
  -h, --help     zz{{Show help message.}}
  -q, --quiet    zz{{Only display errors and warnings.}}
  --usage        zz{{Show usage message and options.}}
  -v, --verbose  zz{{Display more information.}}
}}
zz{{:See also: bar, foo}}
""",
            cmd_WithSeeAlso(),
        )

    def test_get_help_text(self):
        """Commands have a get_help_text method which returns their help."""

        class cmd_Demo(commands.Command):
            __doc__ = """A sample command."""

        self.assertCmdHelp(
            """\
zz{{:Purpose: zz{{A sample command.}}
}}zz{{:Usage:   brz Demo
}}
zz{{:Options:
  -h, --help     zz{{Show help message.}}
  -q, --quiet    zz{{Only display errors and warnings.}}
  --usage        zz{{Show usage message and options.}}
  -v, --verbose  zz{{Display more information.}}
}}
""",
            cmd_Demo(),
        )

    def test_command_with_additional_see_also(self):
        class cmd_WithSeeAlso(commands.Command):
            __doc__ = """A sample command."""
            _see_also = ["foo", "bar"]

        cmd = cmd_WithSeeAlso()
        helptext = cmd.get_help_text(["gam"])
        self.assertEndsWith(
            helptext,
            """\
  -h, --help     zz{{Show help message.}}
  -q, --quiet    zz{{Only display errors and warnings.}}
  --usage        zz{{Show usage message and options.}}
  -v, --verbose  zz{{Display more information.}}
}}
zz{{:See also: bar, foo, gam}}
""",
        )

    def test_command_only_additional_see_also(self):
        class cmd_WithSeeAlso(commands.Command):
            __doc__ = """A sample command."""

        cmd = cmd_WithSeeAlso()
        helptext = cmd.get_help_text(["gam"])
        self.assertEndsWith(
            helptext,
            """\
zz{{:Options:
  -h, --help     zz{{Show help message.}}
  -q, --quiet    zz{{Only display errors and warnings.}}
  --usage        zz{{Show usage message and options.}}
  -v, --verbose  zz{{Display more information.}}
}}
zz{{:See also: gam}}
""",
        )

    def test_help_custom_section_ordering(self):
        """Custom descriptive sections should remain in the order given."""

        # The help formatter expect the class name to start with 'cmd_'
        class cmd_Demo(commands.Command):
            __doc__ = """A sample command.

            Blah blah blah.

            :Formats:
              Interesting stuff about formats.

            :Examples:
              Example 1::

                cmd arg1

            :Tips:
              Clever things to keep in mind.
            """

        self.assertCmdHelp(
            """\
zz{{:Purpose: zz{{A sample command.}}
}}zz{{:Usage:   brz Demo
}}
zz{{:Options:
  -h, --help     zz{{Show help message.}}
  -q, --quiet    zz{{Only display errors and warnings.}}
  --usage        zz{{Show usage message and options.}}
  -v, --verbose  zz{{Display more information.}}
}}
Description:
  zz{{zz{{Blah blah blah.}}

}}:Formats:
  zz{{Interesting stuff about formats.}}

Examples:
  zz{{Example 1::}}

    zz{{cmd arg1}}

Tips:
  zz{{Clever things to keep in mind.}}

""",
            cmd_Demo(),
        )

    def test_help_text_custom_usage(self):
        """Help text may contain a custom usage section."""

        class cmd_Demo(commands.Command):
            __doc__ = """A sample command.

            :Usage:
                cmd Demo [opts] args

                cmd Demo -h

            Blah blah blah.
            """

        self.assertCmdHelp(
            """\
zz{{:Purpose: zz{{A sample command.}}
}}zz{{:Usage:
    zz{{cmd Demo [opts] args}}

    zz{{cmd Demo -h}}

}}
zz{{:Options:
  -h, --help     zz{{Show help message.}}
  -q, --quiet    zz{{Only display errors and warnings.}}
  --usage        zz{{Show usage message and options.}}
  -v, --verbose  zz{{Display more information.}}
}}
Description:
  zz{{zz{{Blah blah blah.}}

}}
""",
            cmd_Demo(),
        )


class TestHelp(tests.TestCase):
    def setUp(self):
        super().setUp()
        commands.install_bzr_command_hooks()


class TestRegisteredTopic(TestHelp):
    """Tests for the RegisteredTopic class."""

    def test_contruct(self):
        """Construction takes the help topic name for the registered item."""
        # validate our test
        self.assertTrue("basic" in help_topics.topic_registry)
        topic = help_topics.RegisteredTopic("basic")
        self.assertEqual("basic", topic.topic)

    def test_get_help_text(self):
        """RegisteredTopic returns the get_detail results for get_help_text."""
        topic = help_topics.RegisteredTopic("commands")
        self.assertEqual(
            help_topics.topic_registry.get_detail("commands"), topic.get_help_text()
        )

    def test_get_help_text_with_additional_see_also(self):
        topic = help_topics.RegisteredTopic("commands")
        self.assertEndsWith(
            topic.get_help_text(["foo", "bar"]), "\nSee also: bar, foo\n"
        )

    def test_get_help_text_loaded_from_file(self):
        # Pick a known topic stored in an external file
        topic = help_topics.RegisteredTopic("authentication")
        self.assertStartsWith(
            topic.get_help_text(),
            "Authentication Settings\n=======================\n\n",
        )

    def test_get_help_topic(self):
        """The help topic for RegisteredTopic is its topic from construction."""
        topic = help_topics.RegisteredTopic("foobar")
        self.assertEqual("foobar", topic.get_help_topic())
        topic = help_topics.RegisteredTopic("baz")
        self.assertEqual("baz", topic.get_help_topic())


class TestTopicIndex(TestHelp):
    """Tests for the HelpTopicIndex class."""

    def test_default_constructable(self):
        help_topics.HelpTopicIndex()

    def test_get_topics_None(self):
        """Searching for None returns the basic help topic."""
        index = help_topics.HelpTopicIndex()
        topics = index.get_topics(None)
        self.assertEqual(1, len(topics))
        self.assertIsInstance(topics[0], help_topics.RegisteredTopic)
        self.assertEqual("basic", topics[0].topic)

    def test_get_topics_topics(self):
        """Searching for a string returns the matching string."""
        index = help_topics.HelpTopicIndex()
        topics = index.get_topics("topics")
        self.assertEqual(1, len(topics))
        self.assertIsInstance(topics[0], help_topics.RegisteredTopic)
        self.assertEqual("topics", topics[0].topic)

    def test_get_topics_no_topic(self):
        """Searching for something not registered returns []."""
        index = help_topics.HelpTopicIndex()
        self.assertEqual([], index.get_topics("nothing by this name"))

    def test_prefix(self):
        """TopicIndex has a prefix of ''."""
        index = help_topics.HelpTopicIndex()
        self.assertEqual("", index.prefix)


class TestConfigOptionIndex(TestHelp):
    """Tests for the HelpCommandIndex class."""

    def setUp(self):
        super().setUp()
        self.index = help_topics.ConfigOptionHelpIndex()

    def test_get_topics_None(self):
        """Searching for None returns an empty list."""
        self.assertEqual([], self.index.get_topics(None))

    def test_get_topics_no_topic(self):
        self.assertEqual([], self.index.get_topics("nothing by this name"))

    def test_prefix(self):
        self.assertEqual("configuration/", self.index.prefix)

    def test_get_topic_with_prefix(self):
        topics = self.index.get_topics("configuration/default_format")
        self.assertLength(1, topics)
        opt = topics[0]
        self.assertIsInstance(opt, config.Option)
        self.assertEqual("default_format", opt.name)


class TestCommandIndex(TestHelp):
    """Tests for the HelpCommandIndex class."""

    def test_default_constructable(self):
        commands.HelpCommandIndex()

    def test_get_topics_None(self):
        """Searching for None returns an empty list."""
        index = commands.HelpCommandIndex()
        self.assertEqual([], index.get_topics(None))

    def test_get_topics_rocks(self):
        """Searching for 'rocks' returns the cmd_rocks command instance."""
        index = commands.HelpCommandIndex()
        topics = index.get_topics("rocks")
        self.assertEqual(1, len(topics))
        self.assertIsInstance(topics[0], builtins.cmd_rocks)

    def test_get_topics_no_topic(self):
        """Searching for something that is not a command returns []."""
        index = commands.HelpCommandIndex()
        self.assertEqual([], index.get_topics("nothing by this name"))

    def test_prefix(self):
        """CommandIndex has a prefix of 'commands/'."""
        index = commands.HelpCommandIndex()
        self.assertEqual("commands/", index.prefix)

    def test_get_topic_with_prefix(self):
        """Searching for commands/rocks returns the rocks command object."""
        index = commands.HelpCommandIndex()
        topics = index.get_topics("commands/rocks")
        self.assertEqual(1, len(topics))
        self.assertIsInstance(topics[0], builtins.cmd_rocks)


class TestHelpIndices(tests.TestCase):
    """Tests for the HelpIndices class."""

    def test_default_search_path(self):
        """The default search path should include internal indexs."""
        indices = help.HelpIndices()
        self.assertEqual(4, len(indices.search_path))
        # help topics should be searched in first.
        self.assertIsInstance(indices.search_path[0], help_topics.HelpTopicIndex)
        # with commands being search second.
        self.assertIsInstance(indices.search_path[1], commands.HelpCommandIndex)
        # plugins are a third index.
        self.assertIsInstance(indices.search_path[2], plugin.PluginsHelpIndex)
        # config options are a fourth index
        self.assertIsInstance(indices.search_path[3], help_topics.ConfigOptionHelpIndex)

    def test_search_for_unknown_topic_raises(self):
        """Searching for an unknown topic should raise NoHelpTopic."""
        indices = help.HelpIndices()
        indices.search_path = []
        error = self.assertRaises(help.NoHelpTopic, indices.search, "foo")
        self.assertEqual("foo", error.topic)

    def test_search_calls_get_topic(self):
        """Searching should call get_topics in all indexes in order."""
        calls = []

        class RecordingIndex:
            def __init__(self, name):
                self.prefix = name

            def get_topics(self, topic):
                calls.append(("get_topics", self.prefix, topic))
                return ["something"]

        index = help.HelpIndices()
        index.search_path = [RecordingIndex("1"), RecordingIndex("2")]
        # try with None
        index.search(None)
        self.assertEqual(
            [
                ("get_topics", "1", None),
                ("get_topics", "2", None),
            ],
            calls,
        )
        # and with a string
        del calls[:]
        index.search("bar")
        self.assertEqual(
            [
                ("get_topics", "1", "bar"),
                ("get_topics", "2", "bar"),
            ],
            calls,
        )

    def test_search_returns_index_and_results(self):
        """Searching should return help topics with their index."""

        class CannedIndex:
            def __init__(self, prefix, search_result):
                self.prefix = prefix
                self.result = search_result

            def get_topics(self, topic):
                return self.result

        index = help.HelpIndices()
        index_one = CannedIndex("1", ["a"])
        index_two = CannedIndex("2", ["b", "c"])
        index.search_path = [index_one, index_two]
        self.assertEqual(
            [(index_one, "a"), (index_two, "b"), (index_two, "c")], index.search(None)
        )

    def test_search_checks_for_duplicate_prefixes(self):
        """Its an error when there are multiple indices with the same prefix."""
        indices = help.HelpIndices()
        indices.search_path = [
            help_topics.HelpTopicIndex(),
            help_topics.HelpTopicIndex(),
        ]
        self.assertRaises(errors.DuplicateHelpPrefix, indices.search, None)
