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
        helpfile = StringIO()
        help.help_on_command_object(cmd, 'cmd_sample', helpfile)
        self.assertEndsWith(
            helpfile.getvalue(),
            '  -h, --help  show help message\n'
            '\n'
            'See also: bar, foo\n')


class TestTopicContext(tests.TestCase):
    """Tests for the HelpTopicContext class."""

    def test_default_constructable(self):
        context = help_topics.HelpTopicContext()


class TestCommandContext(tests.TestCase):
    """Tests for the HelpCommandContext class."""

    def test_default_constructable(self):
        context = commands.HelpCommandContext()


class TestHelpContexts(tests.TestCase):
    """Tests for the HelpContexts class."""

    def test_default_search_path(self):
        """The default search path should include internal contexts."""
        contexts = help.HelpContexts()
        self.assertEqual(2, len(contexts.search_path))
        # help topics should be searched in first.
        self.assertIsInstance(contexts.search_path[0],
            help_topics.HelpTopicContext)
        # with commands being search second.
        self.assertIsInstance(contexts.search_path[1],
            commands.HelpCommandContext)

    def test_search_for_unknown_topic_raises(self):
        """Searching for an unknown topic should raise NoHelpTopic."""
        contexts = help.HelpContexts()
        contexts.search_path = []
        error = self.assertRaises(errors.NoHelpTopic, contexts.search, 'foo')
        self.assertEqual('foo', error.topic)

    def test_search_calls_get_topic(self):
        """Searching should call get_topics in all indexes in order."""
        calls = []
        class RecordingContext(object):
            def __init__(self, name):
                self.name = name
            def get_topics(self, topic):
                calls.append(('get_topics', self.name, topic))
                return ['something']
        contexts = help.HelpContexts()
        contexts.search_path = [RecordingContext('1'), RecordingContext('2')]
        # try with None
        contexts.search(None)
        self.assertEqual([
            ('get_topics', '1', None),
            ('get_topics', '2', None),
            ],
            calls)
        # and with a string
        del calls[:]
        contexts.search('bar')
        self.assertEqual([
            ('get_topics', '1', 'bar'),
            ('get_topics', '2', 'bar'),
            ],
            calls)
