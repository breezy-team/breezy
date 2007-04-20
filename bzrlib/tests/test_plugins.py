# Copyright (C) 2005 Canonical Ltd
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

"""Tests for plugins"""

# XXX: There are no plugin tests at the moment because the plugin module
# affects the global state of the process.  See bzrlib/plugins.py for more
# comments.

import os
from StringIO import StringIO
import sys
import zipfile

from bzrlib import plugin, tests
import bzrlib.plugin
import bzrlib.plugins
import bzrlib.commands
import bzrlib.help
from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.osutils import pathjoin, abspath


PLUGIN_TEXT = """\
import bzrlib.commands
class cmd_myplug(bzrlib.commands.Command):
    '''Just a simple test plugin.'''
    aliases = ['mplg']
    def run(self):
        print 'Hello from my plugin'
"""

# TODO: Write a test for plugin decoration of commands.

class TestLoadingPlugins(TestCaseInTempDir):

    activeattributes = {}

    def test_plugins_with_the_same_name_are_not_loaded(self):
        # This test tests that having two plugins in different directories does
        # not result in both being loaded when they have the same name.  get a
        # file name we can use which is also a valid attribute for accessing in
        # activeattributes. - we cannot give import parameters.
        tempattribute = "0"
        self.failIf(tempattribute in self.activeattributes)
        # set a place for the plugins to record their loading, and at the same
        # time validate that the location the plugins should record to is
        # valid and correct.
        bzrlib.tests.test_plugins.TestLoadingPlugins.activeattributes \
            [tempattribute] = []
        self.failUnless(tempattribute in self.activeattributes)
        # create two plugin directories
        os.mkdir('first')
        os.mkdir('second')
        # write a plugin that will record when its loaded in the 
        # tempattribute list.
        template = ("from bzrlib.tests.test_plugins import TestLoadingPlugins\n"
                    "TestLoadingPlugins.activeattributes[%r].append('%s')\n")
        print >> file(os.path.join('first', 'plugin.py'), 'w'), template % (tempattribute, 'first')
        print >> file(os.path.join('second', 'plugin.py'), 'w'), template % (tempattribute, 'second')
        try:
            bzrlib.plugin.load_from_path(['first', 'second'])
            self.assertEqual(['first'], self.activeattributes[tempattribute])
        finally:
            # remove the plugin 'plugin'
            del self.activeattributes[tempattribute]
            if getattr(bzrlib.plugins, 'plugin', None):
                del bzrlib.plugins.plugin
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))

    def test_plugins_from_different_dirs_can_demand_load(self):
        # This test tests that having two plugins in different
        # directories with different names allows them both to be loaded, when
        # we do a direct import statement.
        # Determine a file name we can use which is also a valid attribute
        # for accessing in activeattributes. - we cannot give import parameters.
        tempattribute = "different-dirs"
        self.failIf(tempattribute in self.activeattributes)
        # set a place for the plugins to record their loading, and at the same
        # time validate that the location the plugins should record to is
        # valid and correct.
        bzrlib.tests.test_plugins.TestLoadingPlugins.activeattributes \
            [tempattribute] = []
        self.failUnless(tempattribute in self.activeattributes)
        # create two plugin directories
        os.mkdir('first')
        os.mkdir('second')
        # write plugins that will record when they are loaded in the 
        # tempattribute list.
        template = ("from bzrlib.tests.test_plugins import TestLoadingPlugins\n"
                    "TestLoadingPlugins.activeattributes[%r].append('%s')\n")
        print >> file(os.path.join('first', 'pluginone.py'), 'w'), template % (tempattribute, 'first')
        print >> file(os.path.join('second', 'plugintwo.py'), 'w'), template % (tempattribute, 'second')
        oldpath = bzrlib.plugins.__path__
        try:
            bzrlib.plugins.__path__ = ['first', 'second']
            exec "import bzrlib.plugins.pluginone"
            self.assertEqual(['first'], self.activeattributes[tempattribute])
            exec "import bzrlib.plugins.plugintwo"
            self.assertEqual(['first', 'second'],
                self.activeattributes[tempattribute])
        finally:
            # remove the plugin 'plugin'
            del self.activeattributes[tempattribute]
            if getattr(bzrlib.plugins, 'plugin', None):
                del bzrlib.plugins.plugin
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))


class TestAllPlugins(TestCaseInTempDir):

    def test_plugin_appears_in_all_plugins(self):
        # This test tests a new plugin appears in bzrlib.plugin.all_plugins().
        # check the plugin is not loaded already
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))
        # write a plugin that _cannot_ fail to load.
        print >> file('plugin.py', 'w'), ""
        try:
            bzrlib.plugin.load_from_path(['.'])
            self.failUnless('plugin' in bzrlib.plugin.all_plugins())
            self.failUnless(getattr(bzrlib.plugins, 'plugin', None))
            self.assertEqual(bzrlib.plugin.all_plugins()['plugin'],
                             bzrlib.plugins.plugin)
        finally:
            # remove the plugin 'plugin'
            if 'bzrlib.plugins.plugin' in sys.modules:
                del sys.modules['bzrlib.plugins.plugin']
            if getattr(bzrlib.plugins, 'plugin', None):
                del bzrlib.plugins.plugin
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))


class TestPluginHelp(TestCaseInTempDir):

    def split_help_commands(self):
        help = {}
        current = None
        for line in self.capture('help commands').splitlines():
            if not line.startswith(' '):
                current = line.split()[0]
            help[current] = help.get(current, '') + line

        return help

    def test_plugin_help_builtins_unaffected(self):
        # Check we don't get false positives
        help_commands = self.split_help_commands()
        for cmd_name in bzrlib.commands.builtin_command_names():
            if cmd_name in bzrlib.commands.plugin_command_names():
                continue
            try:
                help = bzrlib.commands.get_cmd_object(cmd_name).get_help_text()
            except NotImplementedError:
                # some commands have no help
                pass
            else:
                self.assertNotContainsRe(help, 'From plugin "[^"]*"')

            if cmd_name in help_commands.keys():
                # some commands are hidden
                help = help_commands[cmd_name]
                self.assertNotContainsRe(help, 'From plugin "[^"]*"')

    def test_plugin_help_shows_plugin(self):
        # Create a test plugin
        os.mkdir('plugin_test')
        f = open(pathjoin('plugin_test', 'myplug.py'), 'w')
        f.write(PLUGIN_TEXT)
        f.close()

        try:
            # Check its help
            bzrlib.plugin.load_from_path(['plugin_test'])
            bzrlib.commands.register_command( bzrlib.plugins.myplug.cmd_myplug)
            help = self.capture('help myplug')
            self.assertContainsRe(help, 'From plugin "myplug"')
            help = self.split_help_commands()['myplug']
            self.assertContainsRe(help, '\[myplug\]')
        finally:
            # unregister command
            if bzrlib.commands.plugin_cmds.get('myplug', None):
                del bzrlib.commands.plugin_cmds['myplug']
            # remove the plugin 'myplug'
            if getattr(bzrlib.plugins, 'myplug', None):
                delattr(bzrlib.plugins, 'myplug')


class TestPluginFromZip(TestCaseInTempDir):

    def make_zipped_plugin(self, zip_name, filename):
        z = zipfile.ZipFile(zip_name, 'w')
        z.writestr(filename, PLUGIN_TEXT)
        z.close()

    def check_plugin_load(self, zip_name, plugin_name):
        self.assertFalse(plugin_name in dir(bzrlib.plugins),
                         'Plugin already loaded')
        try:
            bzrlib.plugin.load_from_zip(zip_name)
            self.assertTrue(plugin_name in dir(bzrlib.plugins),
                            'Plugin is not loaded')
        finally:
            # unregister plugin
            if getattr(bzrlib.plugins, plugin_name, None):
                delattr(bzrlib.plugins, plugin_name)

    def test_load_module(self):
        self.make_zipped_plugin('./test.zip', 'ziplug.py')
        self.check_plugin_load('./test.zip', 'ziplug')

    def test_load_package(self):
        self.make_zipped_plugin('./test.zip', 'ziplug/__init__.py')
        self.check_plugin_load('./test.zip', 'ziplug')


class TestSetPluginsPath(TestCase):
    
    def test_set_plugins_path(self):
        """set_plugins_path should set the module __path__ correctly."""
        old_path = bzrlib.plugins.__path__
        try:
            bzrlib.plugins.__path__ = []
            expected_path = bzrlib.plugin.set_plugins_path()
            self.assertEqual(expected_path, bzrlib.plugins.__path__)
        finally:
            bzrlib.plugins.__path__ = old_path


class TestHelpIndex(tests.TestCase):
    """Tests for the PluginsHelpIndex class."""

    def test_default_constructable(self):
        index = plugin.PluginsHelpIndex()

    def test_get_topics_None(self):
        """Searching for None returns an empty list."""
        index = plugin.PluginsHelpIndex()
        self.assertEqual([], index.get_topics(None))

    def test_get_topics_launchpad(self):
        """Searching for 'launchpad' returns the launchpad plugin docstring."""
        index = plugin.PluginsHelpIndex()
        # if bzr was run with '--no-plugins' we need to manually load the
        # reference plugin. Its shipped with bzr, and loading at this point
        # won't add additional tests to run.
        import bzrlib.plugins.launchpad
        topics = index.get_topics('launchpad')
        self.assertEqual(1, len(topics))
        self.assertIsInstance(topics[0], plugin.ModuleHelpTopic)
        self.assertEqual(bzrlib.plugins.launchpad, topics[0].module)

    def test_get_topics_no_topic(self):
        """Searching for something that is not a plugin returns []."""
        # test this by using a name that cannot be a plugin - its not
        # a valid python identifier.
        index = plugin.PluginsHelpIndex()
        self.assertEqual([], index.get_topics('nothing by this name'))

    def test_prefix(self):
        """PluginsHelpIndex has a prefix of 'plugins/'."""
        index = plugin.PluginsHelpIndex()
        self.assertEqual('plugins/', index.prefix)

    def test_get_topic_with_prefix(self):
        """Searching for plugins/launchpad returns launchpad module help."""
        index = plugin.PluginsHelpIndex()
        # if bzr was run with '--no-plugins' we need to manually load the
        # reference plugin. Its shipped with bzr, and loading at this point
        # won't add additional tests to run.
        import bzrlib.plugins.launchpad
        topics = index.get_topics('plugins/launchpad')
        self.assertEqual(1, len(topics))
        self.assertIsInstance(topics[0], plugin.ModuleHelpTopic)
        self.assertEqual(bzrlib.plugins.launchpad, topics[0].module)


class FakeModule(object):
    """A fake module to test with."""

    def __init__(self, doc, name):
        self.__doc__ = doc
        self.__name__ = name


class TestModuleHelpTopic(tests.TestCase):
    """Tests for the ModuleHelpTopic class."""

    def test_contruct(self):
        """Construction takes the module to document."""
        mod = FakeModule('foo', 'foo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual(mod, topic.module)

    def test_get_help_text_None(self):
        """A ModuleHelpTopic returns the docstring for get_help_text."""
        mod = FakeModule(None, 'demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("Plugin 'demo' has no docstring.\n",
            topic.get_help_text())

    def test_get_help_text_no_carriage_return(self):
        """ModuleHelpTopic.get_help_text adds a \n if needed."""
        mod = FakeModule('one line of help', 'demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("one line of help\n",
            topic.get_help_text())

    def test_get_help_text_carriage_return(self):
        """ModuleHelpTopic.get_help_text adds a \n if needed."""
        mod = FakeModule('two lines of help\nand more\n', 'demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("two lines of help\nand more\n",
            topic.get_help_text())

    def test_get_help_text_with_additional_see_also(self):
        mod = FakeModule('two lines of help\nand more', 'demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("two lines of help\nand more\nSee also: bar, foo\n",
            topic.get_help_text(['foo', 'bar']))
