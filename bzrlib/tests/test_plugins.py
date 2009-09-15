# Copyright (C) 2005, 2007 Canonical Ltd
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

"""Tests for plugins"""

# XXX: There are no plugin tests at the moment because the plugin module
# affects the global state of the process.  See bzrlib/plugins.py for more
# comments.

import logging
import os
from StringIO import StringIO
import sys
import zipfile

from bzrlib import plugin, tests
import bzrlib.plugin
import bzrlib.plugins
import bzrlib.commands
import bzrlib.help
from bzrlib.tests import (
    TestCase,
    TestCaseInTempDir,
    TestUtil,
    )
from bzrlib.osutils import pathjoin, abspath, normpath


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

        outfile = open(os.path.join('first', 'plugin.py'), 'w')
        try:
            outfile.write(template % (tempattribute, 'first'))
            outfile.write('\n')
        finally:
            outfile.close()

        outfile = open(os.path.join('second', 'plugin.py'), 'w')
        try:
            outfile.write(template % (tempattribute, 'second'))
            outfile.write('\n')
        finally:
            outfile.close()

        try:
            bzrlib.plugin.load_from_path(['first', 'second'])
            self.assertEqual(['first'], self.activeattributes[tempattribute])
        finally:
            # remove the plugin 'plugin'
            del self.activeattributes[tempattribute]
            if 'bzrlib.plugins.plugin' in sys.modules:
                del sys.modules['bzrlib.plugins.plugin']
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

        outfile = open(os.path.join('first', 'pluginone.py'), 'w')
        try:
            outfile.write(template % (tempattribute, 'first'))
            outfile.write('\n')
        finally:
            outfile.close()

        outfile = open(os.path.join('second', 'plugintwo.py'), 'w')
        try:
            outfile.write(template % (tempattribute, 'second'))
            outfile.write('\n')
        finally:
            outfile.close()

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
            if getattr(bzrlib.plugins, 'pluginone', None):
                del bzrlib.plugins.pluginone
            if getattr(bzrlib.plugins, 'plugintwo', None):
                del bzrlib.plugins.plugintwo
        self.failIf(getattr(bzrlib.plugins, 'pluginone', None))
        self.failIf(getattr(bzrlib.plugins, 'plugintwo', None))

    def test_plugins_can_load_from_directory_with_trailing_slash(self):
        # This test tests that a plugin can load from a directory when the
        # directory in the path has a trailing slash.
        # check the plugin is not loaded already
        self.failIf(getattr(bzrlib.plugins, 'ts_plugin', None))
        tempattribute = "trailing-slash"
        self.failIf(tempattribute in self.activeattributes)
        # set a place for the plugin to record its loading, and at the same
        # time validate that the location the plugin should record to is
        # valid and correct.
        bzrlib.tests.test_plugins.TestLoadingPlugins.activeattributes \
            [tempattribute] = []
        self.failUnless(tempattribute in self.activeattributes)
        # create a directory for the plugin
        os.mkdir('plugin_test')
        # write a plugin that will record when its loaded in the
        # tempattribute list.
        template = ("from bzrlib.tests.test_plugins import TestLoadingPlugins\n"
                    "TestLoadingPlugins.activeattributes[%r].append('%s')\n")

        outfile = open(os.path.join('plugin_test', 'ts_plugin.py'), 'w')
        try:
            outfile.write(template % (tempattribute, 'plugin'))
            outfile.write('\n')
        finally:
            outfile.close()

        try:
            bzrlib.plugin.load_from_path(['plugin_test'+os.sep])
            self.assertEqual(['plugin'], self.activeattributes[tempattribute])
        finally:
            # remove the plugin 'plugin'
            del self.activeattributes[tempattribute]
            if getattr(bzrlib.plugins, 'ts_plugin', None):
                del bzrlib.plugins.ts_plugin
        self.failIf(getattr(bzrlib.plugins, 'ts_plugin', None))

    def load_and_capture(self, name):
        """Load plugins from '.' capturing the output.

        :param name: The name of the plugin.
        :return: A string with the log from the plugin loading call.
        """
        # Capture output
        stream = StringIO()
        try:
            handler = logging.StreamHandler(stream)
            log = logging.getLogger('bzr')
            log.addHandler(handler)
            try:
                try:
                    bzrlib.plugin.load_from_path(['.'])
                finally:
                    if 'bzrlib.plugins.%s' % name in sys.modules:
                        del sys.modules['bzrlib.plugins.%s' % name]
                    if getattr(bzrlib.plugins, name, None):
                        delattr(bzrlib.plugins, name)
            finally:
                # Stop capturing output
                handler.flush()
                handler.close()
                log.removeHandler(handler)
            return stream.getvalue()
        finally:
            stream.close()

    def test_plugin_with_bad_api_version_reports(self):
        # This plugin asks for bzrlib api version 1.0.0, which is not supported
        # anymore.
        name = 'wants100.py'
        f = file(name, 'w')
        try:
            f.write("import bzrlib.api\n"
                "bzrlib.api.require_any_api(bzrlib, [(1, 0, 0)])\n")
        finally:
            f.close()

        log = self.load_and_capture(name)
        self.assertContainsRe(log,
            r"It requested API version")

    def test_plugin_with_bad_name_does_not_load(self):
        # The file name here invalid for a python module.
        name = 'bzr-bad plugin-name..py'
        file(name, 'w').close()
        log = self.load_and_capture(name)
        self.assertContainsRe(log,
            r"Unable to load 'bzr-bad plugin-name\.' in '\.' as a plugin "
            "because the file path isn't a valid module name; try renaming "
            "it to 'bad_plugin_name_'\.")


class TestPlugins(TestCaseInTempDir):

    def setup_plugin(self, source=""):
        # This test tests a new plugin appears in bzrlib.plugin.plugins().
        # check the plugin is not loaded already
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))
        # write a plugin that _cannot_ fail to load.
        file('plugin.py', 'w').write(source + '\n')
        self.addCleanup(self.teardown_plugin)
        bzrlib.plugin.load_from_path(['.'])

    def teardown_plugin(self):
        # remove the plugin 'plugin'
        if 'bzrlib.plugins.plugin' in sys.modules:
            del sys.modules['bzrlib.plugins.plugin']
        if getattr(bzrlib.plugins, 'plugin', None):
            del bzrlib.plugins.plugin
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))

    def test_plugin_appears_in_plugins(self):
        self.setup_plugin()
        self.failUnless('plugin' in bzrlib.plugin.plugins())
        self.failUnless(getattr(bzrlib.plugins, 'plugin', None))
        plugins = bzrlib.plugin.plugins()
        plugin = plugins['plugin']
        self.assertIsInstance(plugin, bzrlib.plugin.PlugIn)
        self.assertEqual(bzrlib.plugins.plugin, plugin.module)

    def test_trivial_plugin_get_path(self):
        self.setup_plugin()
        plugins = bzrlib.plugin.plugins()
        plugin = plugins['plugin']
        plugin_path = self.test_dir + '/plugin.py'
        self.assertIsSameRealPath(plugin_path, normpath(plugin.path()))

    def test_plugin_get_path_py_not_pyc(self):
        self.setup_plugin()         # after first import there will be plugin.pyc
        self.teardown_plugin()
        bzrlib.plugin.load_from_path(['.']) # import plugin.pyc
        plugins = bzrlib.plugin.plugins()
        plugin = plugins['plugin']
        plugin_path = self.test_dir + '/plugin.py'
        self.assertIsSameRealPath(plugin_path, normpath(plugin.path()))

    def test_plugin_get_path_pyc_only(self):
        self.setup_plugin()         # after first import there will be plugin.pyc
        self.teardown_plugin()
        os.unlink(self.test_dir + '/plugin.py')
        bzrlib.plugin.load_from_path(['.']) # import plugin.pyc
        plugins = bzrlib.plugin.plugins()
        plugin = plugins['plugin']
        if __debug__:
            plugin_path = self.test_dir + '/plugin.pyc'
        else:
            plugin_path = self.test_dir + '/plugin.pyo'
        self.assertIsSameRealPath(plugin_path, normpath(plugin.path()))

    def test_no_test_suite_gives_None_for_test_suite(self):
        self.setup_plugin()
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual(None, plugin.test_suite())

    def test_test_suite_gives_test_suite_result(self):
        source = """def test_suite(): return 'foo'"""
        self.setup_plugin(source)
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual('foo', plugin.test_suite())

    def test_no_load_plugin_tests_gives_None_for_load_plugin_tests(self):
        self.setup_plugin()
        loader = TestUtil.TestLoader()
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual(None, plugin.load_plugin_tests(loader))

    def test_load_plugin_tests_gives_load_plugin_tests_result(self):
        source = """
def load_tests(standard_tests, module, loader):
    return 'foo'"""
        self.setup_plugin(source)
        loader = TestUtil.TestLoader()
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual('foo', plugin.load_plugin_tests(loader))

    def test_no_version_info(self):
        self.setup_plugin()
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual(None, plugin.version_info())

    def test_with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'dev', 4)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual((1, 2, 3, 'dev', 4), plugin.version_info())

    def test_short_version_info_gets_padded(self):
        # the gtk plugin has version_info = (1,2,3) rather than the 5-tuple.
        # so we adapt it
        self.setup_plugin("version_info = (1, 2, 3)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual((1, 2, 3, 'final', 0), plugin.version_info())

    def test_no_version_info___version__(self):
        self.setup_plugin()
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("unknown", plugin.__version__)

    def test_str__version__with_version_info(self):
        self.setup_plugin("version_info = '1.2.3'")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1.2.3", plugin.__version__)

    def test_noniterable__version__with_version_info(self):
        self.setup_plugin("version_info = (1)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1", plugin.__version__)

    def test_1__version__with_version_info(self):
        self.setup_plugin("version_info = (1,)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1", plugin.__version__)

    def test_1_2__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1.2", plugin.__version__)

    def test_1_2_3__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1.2.3", plugin.__version__)

    def test_candidate__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'candidate', 1)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1.2.3rc1", plugin.__version__)

    def test_dev__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'dev', 0)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1.2.3dev", plugin.__version__)

    def test_dev_fallback__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'dev', 4)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1.2.3dev4", plugin.__version__)

    def test_final__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'final', 0)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1.2.3", plugin.__version__)

    def test_final_fallback__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'final', 2)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1.2.3.final.2", plugin.__version__)


class TestPluginHelp(TestCaseInTempDir):

    def split_help_commands(self):
        help = {}
        current = None
        out, err = self.run_bzr('--no-plugins help commands')
        for line in out.splitlines():
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
                self.assertNotContainsRe(help, 'plugin "[^"]*"')

            if cmd_name in help_commands.keys():
                # some commands are hidden
                help = help_commands[cmd_name]
                self.assertNotContainsRe(help, 'plugin "[^"]*"')

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
            help = self.run_bzr('help myplug')[0]
            self.assertContainsRe(help, 'plugin "myplug"')
            help = self.split_help_commands()['myplug']
            self.assertContainsRe(help, '\[myplug\]')
        finally:
            # unregister command
            if 'myplug' in bzrlib.commands.plugin_cmds:
                bzrlib.commands.plugin_cmds.remove('myplug')
            # remove the plugin 'myplug'
            if getattr(bzrlib.plugins, 'myplug', None):
                delattr(bzrlib.plugins, 'myplug')


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

    def test_set_plugins_path_with_trailing_slashes(self):
        """set_plugins_path should set the module __path__ based on
        BZR_PLUGIN_PATH after removing all trailing slashes."""
        old_path = bzrlib.plugins.__path__
        old_env = os.environ.get('BZR_PLUGIN_PATH')
        try:
            bzrlib.plugins.__path__ = []
            os.environ['BZR_PLUGIN_PATH'] = "first\\//\\" + os.pathsep + \
                "second/\\/\\/"
            bzrlib.plugin.set_plugins_path()
            # We expect our nominated paths to have all path-seps removed,
            # and this is testing only that.
            expected_path = ['first', 'second']
            self.assertEqual(expected_path,
                bzrlib.plugins.__path__[:len(expected_path)])
        finally:
            bzrlib.plugins.__path__ = old_path
            if old_env is not None:
                os.environ['BZR_PLUGIN_PATH'] = old_env
            else:
                del os.environ['BZR_PLUGIN_PATH']


class TestHelpIndex(tests.TestCase):
    """Tests for the PluginsHelpIndex class."""

    def test_default_constructable(self):
        index = plugin.PluginsHelpIndex()

    def test_get_topics_None(self):
        """Searching for None returns an empty list."""
        index = plugin.PluginsHelpIndex()
        self.assertEqual([], index.get_topics(None))

    def test_get_topics_for_plugin(self):
        """Searching for plugin name gets its docstring."""
        index = plugin.PluginsHelpIndex()
        # make a new plugin here for this test, even if we're run with
        # --no-plugins
        self.assertFalse(sys.modules.has_key('bzrlib.plugins.demo_module'))
        demo_module = FakeModule('', 'bzrlib.plugins.demo_module')
        sys.modules['bzrlib.plugins.demo_module'] = demo_module
        try:
            topics = index.get_topics('demo_module')
            self.assertEqual(1, len(topics))
            self.assertIsInstance(topics[0], plugin.ModuleHelpTopic)
            self.assertEqual(demo_module, topics[0].module)
        finally:
            del sys.modules['bzrlib.plugins.demo_module']

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

    def test_get_plugin_topic_with_prefix(self):
        """Searching for plugins/demo_module returns help."""
        index = plugin.PluginsHelpIndex()
        self.assertFalse(sys.modules.has_key('bzrlib.plugins.demo_module'))
        demo_module = FakeModule('', 'bzrlib.plugins.demo_module')
        sys.modules['bzrlib.plugins.demo_module'] = demo_module
        try:
            topics = index.get_topics('plugins/demo_module')
            self.assertEqual(1, len(topics))
            self.assertIsInstance(topics[0], plugin.ModuleHelpTopic)
            self.assertEqual(demo_module, topics[0].module)
        finally:
            del sys.modules['bzrlib.plugins.demo_module']


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

    def test_get_help_topic(self):
        """The help topic for a plugin is its module name."""
        mod = FakeModule('two lines of help\nand more', 'bzrlib.plugins.demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual('demo', topic.get_help_topic())
        mod = FakeModule('two lines of help\nand more', 'bzrlib.plugins.foo_bar')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual('foo_bar', topic.get_help_topic())


def clear_plugins(test_case):
    # Save the attributes that we're about to monkey-patch.
    old_plugins_path = bzrlib.plugins.__path__
    old_loaded = plugin._loaded
    old_load_from_path = plugin.load_from_path
    # Change bzrlib.plugin to think no plugins have been loaded yet.
    bzrlib.plugins.__path__ = []
    plugin._loaded = False
    # Monkey-patch load_from_path to stop it from actually loading anything.
    def load_from_path(dirs):
        pass
    plugin.load_from_path = load_from_path
    def restore_plugins():
        bzrlib.plugins.__path__ = old_plugins_path
        plugin._loaded = old_loaded
        plugin.load_from_path = old_load_from_path
    test_case.addCleanup(restore_plugins)


class TestPluginPaths(tests.TestCase):

    def test_set_plugins_path_with_args(self):
        clear_plugins(self)
        plugin.set_plugins_path(['a', 'b'])
        self.assertEqual(['a', 'b'], bzrlib.plugins.__path__)

    def test_set_plugins_path_defaults(self):
        clear_plugins(self)
        plugin.set_plugins_path()
        self.assertEqual(plugin.get_standard_plugins_path(),
                         bzrlib.plugins.__path__)

    def test_get_standard_plugins_path(self):
        path = plugin.get_standard_plugins_path()
        self.assertEqual(plugin.get_default_plugin_path(), path[0])
        for directory in path:
            self.assertNotContainsRe(directory, r'\\/$')
        try:
            from distutils.sysconfig import get_python_lib
        except ImportError:
            pass
        else:
            if sys.platform != 'win32':
                python_lib = get_python_lib()
                for directory in path:
                    if directory.startswith(python_lib):
                        break
                else:
                    self.fail('No path to global plugins')

    def test_get_standard_plugins_path_env(self):
        os.environ['BZR_PLUGIN_PATH'] = 'foo/'
        self.assertEqual('foo', plugin.get_standard_plugins_path()[0])


class TestLoadPlugins(tests.TestCaseInTempDir):

    def test_load_plugins(self):
        clear_plugins(self)
        plugin.load_plugins(['.'])
        self.assertEqual(bzrlib.plugins.__path__, ['.'])
        # subsequent loads are no-ops
        plugin.load_plugins(['foo'])
        self.assertEqual(bzrlib.plugins.__path__, ['.'])

    def test_load_plugins_default(self):
        clear_plugins(self)
        plugin.load_plugins()
        path = plugin.get_standard_plugins_path()
        self.assertEqual(path, bzrlib.plugins.__path__)
