# Copyright (C) 2007 Canonical Ltd
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

"""Unit tests for the bzrlib.help module."""

from cStringIO import StringIO

from bzrlib import (
    builtins,
    commands,
    errors,
    help,
    help_topics,
    tests,
    )


class TestCommandHelp(tests.TestCase):
    """Tests for help on commands."""

    def test_command_help_includes_see_also(self):
        class cmd_WithSeeAlso(commands.Command):
            """A sample command."""
            _see_also = ['foo', 'bar']
        cmd = cmd_WithSeeAlso()
        helptext = cmd.get_help_text()
        self.assertEndsWith(
            helptext,
            '  -h, --help  show help message\n'
            '\n'
            'See also: bar, foo\n')

    def test_get_help_text(self):
        """Commands have a get_help_text method which returns their help."""
        class cmd_Demo(commands.Command):
            """A sample command."""
        cmd = cmd_Demo()
        helptext = cmd.get_help_text()
        self.assertStartsWith(helptext, 'usage:bzr Demo')
        self.assertEndsWith(helptext, 'show help message\n')
    

class TestRegisteredTopic(tests.TestCase):
    """Tests for the RegisteredTopic class."""

    def test_contruct(self):
        """Construction takes the help topic name for the registered item."""
        # validate our test 
        self.assertTrue('basic' in help_topics.topic_registry)
        topic = help_topics.RegisteredTopic('basic')
        self.assertEqual('basic', topic.topic)

    def test_get_help_text(self):
        """A RegisteredTopic returns the get_detail results for get_help_text."""
        topic = help_topics.RegisteredTopic('commands')
        self.assertEqual(help_topics.topic_registry.get_detail('commands'),
            topic.get_help_text())


class TestTopicIndex(tests.TestCase):
    """Tests for the HelpTopicIndex class."""

    def test_default_constructable(self):
        index = help_topics.HelpTopicIndex()

    def test_get_topics_None(self):
        """Searching for None returns the basic help topic."""
        index = help_topics.HelpTopicIndex()
        topics = index.get_topics(None)
        self.assertEqual(1, len(topics))
        self.assertIsInstance(topics[0], help_topics.RegisteredTopic)
        self.assertEqual('basic', topics[0].topic)

    def test_get_topics_topics(self):
        """Searching for a string returns the matching string."""
        index = help_topics.HelpTopicIndex()
        topics = index.get_topics('topics')
        self.assertEqual(1, len(topics))
        self.assertIsInstance(topics[0], help_topics.RegisteredTopic)
        self.assertEqual('topics', topics[0].topic)

    def test_get_topics_no_topic(self):
        """Searching for something not registered returns []."""
        index = help_topics.HelpTopicIndex()
        self.assertEqual([], index.get_topics('nothing by this name'))


class TestCommandIndex(tests.TestCase):
    """Tests for the HelpCommandIndex class."""

    def test_default_constructable(self):
        index = commands.HelpCommandIndex()

    def test_get_topics_None(self):
        """Searching for None returns an empty list."""
        index = commands.HelpCommandIndex()
        self.assertEqual([], index.get_topics(None))

    def test_get_topics_rocks(self):
        """Searching for 'rocks' returns the cmd_rocks command instance."""
        index = commands.HelpCommandIndex()
        topics = index.get_topics('rocks')
        self.assertEqual(1, len(topics))
        self.assertIsInstance(topics[0], builtins.cmd_rocks)

    def test_get_topics_no_topic(self):
        """Searching for something that is not a command returns []."""
        index = commands.HelpCommandIndex()
        self.assertEqual([], index.get_topics('nothing by this name'))


class TestHelpIndexs(tests.TestCase):
    """Tests for the HelpIndexs class."""

    def test_default_search_path(self):
        """The default search path should include internal indexs."""
        indexs = help.HelpIndexs()
        self.assertEqual(2, len(indexs.search_path))
        # help topics should be searched in first.
        self.assertIsInstance(indexs.search_path[0],
            help_topics.HelpTopicIndex)
        # with commands being search second.
        self.assertIsInstance(indexs.search_path[1],
            commands.HelpCommandIndex)

    def test_search_for_unknown_topic_raises(self):
        """Searching for an unknown topic should raise NoHelpTopic."""
        indexs = help.HelpIndexs()
        indexs.search_path = []
        error = self.assertRaises(errors.NoHelpTopic, indexs.search, 'foo')
        self.assertEqual('foo', error.topic)

    def test_search_calls_get_topic(self):
        """Searching should call get_topics in all indexes in order."""
        calls = []
        class RecordingIndex(object):
            def __init__(self, name):
                self.name = name
            def get_topics(self, topic):
                calls.append(('get_topics', self.name, topic))
                return ['something']
        index = help.HelpIndexs()
        index.search_path = [RecordingIndex('1'), RecordingIndex('2')]
        # try with None
        index.search(None)
        self.assertEqual([
            ('get_topics', '1', None),
            ('get_topics', '2', None),
            ],
            calls)
        # and with a string
        del calls[:]
        index.search('bar')
        self.assertEqual([
            ('get_topics', '1', 'bar'),
            ('get_topics', '2', 'bar'),
            ],
            calls)

    def test_search_returns_index_results(self):
        """Searching should return all the help topics found."""
        class CannedIndex(object):
            def __init__(self, search_result):
                self.result = search_result
            def get_topics(self, topic):
                return self.result
        index = help.HelpIndexs()
        index.search_path = [CannedIndex(['a']), CannedIndex(['b', 'c'])]
        self.assertEqual(['a', 'b', 'c'], index.search(None))
