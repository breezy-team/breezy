# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

from cStringIO import StringIO
import logging
import os
import sys

import bzrlib
from bzrlib import (
    errors,
    osutils,
    plugin,
    plugins,
    tests,
    trace,
    )


# TODO: Write a test for plugin decoration of commands.

class BaseTestPlugins(tests.TestCaseInTempDir):

    def create_plugin(self, name, source=None, dir='.', file_name=None):
        if source is None:
            source = '''\
"""This is the doc for %s"""
''' % (name)
        if file_name is None:
            file_name = name + '.py'
        # 'source' must not fail to load
        path = osutils.pathjoin(dir, file_name)
        f = open(path, 'w')
        self.addCleanup(os.unlink, path)
        try:
            f.write(source + '\n')
        finally:
            f.close()

    def create_plugin_package(self, name, dir=None, source=None):
        if dir is None:
            dir = name
        if source is None:
            source = '''\
"""This is the doc for %s"""
dir_source = '%s'
''' % (name, dir)
        os.makedirs(dir)
        def cleanup():
            # Workaround lazy import random? madness
            osutils.rmtree(dir)
        self.addCleanup(cleanup)
        self.create_plugin(name, source, dir,
                           file_name='__init__.py')

    def _unregister_plugin(self, name):
        """Remove the plugin from sys.modules and the bzrlib namespace."""
        py_name = 'bzrlib.plugins.%s' % name
        if py_name in sys.modules:
            del sys.modules[py_name]
        if getattr(bzrlib.plugins, name, None) is not None:
            delattr(bzrlib.plugins, name)

    def _unregister_plugin_submodule(self, plugin_name, submodule_name):
        """Remove the submodule from sys.modules and the bzrlib namespace."""
        py_name = 'bzrlib.plugins.%s.%s' % (plugin_name, submodule_name)
        if py_name in sys.modules:
            del sys.modules[py_name]
        plugin = getattr(bzrlib.plugins, plugin_name, None)
        if plugin is not None:
            if getattr(plugin, submodule_name, None) is not None:
                delattr(plugin, submodule_name)

    def assertPluginUnknown(self, name):
        self.assertFalse(getattr(bzrlib.plugins, name, None) is not None)
        self.assertFalse('bzrlib.plugins.%s' % name in sys.modules)

    def assertPluginKnown(self, name):
        self.assertTrue(getattr(bzrlib.plugins, name, None) is not None)
        self.assertTrue('bzrlib.plugins.%s' % name in sys.modules)


class TestLoadingPlugins(BaseTestPlugins):

    activeattributes = {}

    def test_plugins_with_the_same_name_are_not_loaded(self):
        # This test tests that having two plugins in different directories does
        # not result in both being loaded when they have the same name.  get a
        # file name we can use which is also a valid attribute for accessing in
        # activeattributes. - we cannot give import parameters.
        tempattribute = "0"
        self.assertFalse(tempattribute in self.activeattributes)
        # set a place for the plugins to record their loading, and at the same
        # time validate that the location the plugins should record to is
        # valid and correct.
        self.__class__.activeattributes [tempattribute] = []
        self.assertTrue(tempattribute in self.activeattributes)
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
            self._unregister_plugin('plugin')
        self.assertPluginUnknown('plugin')

    def test_plugins_from_different_dirs_can_demand_load(self):
        self.assertFalse('bzrlib.plugins.pluginone' in sys.modules)
        self.assertFalse('bzrlib.plugins.plugintwo' in sys.modules)
        # This test tests that having two plugins in different
        # directories with different names allows them both to be loaded, when
        # we do a direct import statement.
        # Determine a file name we can use which is also a valid attribute
        # for accessing in activeattributes. - we cannot give import parameters.
        tempattribute = "different-dirs"
        self.assertFalse(tempattribute in self.activeattributes)
        # set a place for the plugins to record their loading, and at the same
        # time validate that the location the plugins should record to is
        # valid and correct.
        bzrlib.tests.test_plugins.TestLoadingPlugins.activeattributes \
            [tempattribute] = []
        self.assertTrue(tempattribute in self.activeattributes)
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
            self.assertFalse('bzrlib.plugins.pluginone' in sys.modules)
            self.assertFalse('bzrlib.plugins.plugintwo' in sys.modules)
            bzrlib.plugins.__path__ = ['first', 'second']
            exec "import bzrlib.plugins.pluginone"
            self.assertEqual(['first'], self.activeattributes[tempattribute])
            exec "import bzrlib.plugins.plugintwo"
            self.assertEqual(['first', 'second'],
                self.activeattributes[tempattribute])
        finally:
            # remove the plugin 'plugin'
            del self.activeattributes[tempattribute]
            self._unregister_plugin('pluginone')
            self._unregister_plugin('plugintwo')
        self.assertPluginUnknown('pluginone')
        self.assertPluginUnknown('plugintwo')

    def test_plugins_can_load_from_directory_with_trailing_slash(self):
        # This test tests that a plugin can load from a directory when the
        # directory in the path has a trailing slash.
        # check the plugin is not loaded already
        self.assertPluginUnknown('ts_plugin')
        tempattribute = "trailing-slash"
        self.assertFalse(tempattribute in self.activeattributes)
        # set a place for the plugin to record its loading, and at the same
        # time validate that the location the plugin should record to is
        # valid and correct.
        bzrlib.tests.test_plugins.TestLoadingPlugins.activeattributes \
            [tempattribute] = []
        self.assertTrue(tempattribute in self.activeattributes)
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
            del self.activeattributes[tempattribute]
            self._unregister_plugin('ts_plugin')
        self.assertPluginUnknown('ts_plugin')

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
        """Try loading a plugin that requests an unsupported api.
        
        Observe that it records the problem but doesn't complain on stderr.

        See https://bugs.launchpad.net/bzr/+bug/704195
        """
        self.overrideAttr(plugin, 'plugin_warnings', {})
        name = 'wants100.py'
        f = file(name, 'w')
        try:
            f.write("import bzrlib.api\n"
                "bzrlib.api.require_any_api(bzrlib, [(1, 0, 0)])\n")
        finally:
            f.close()
        log = self.load_and_capture(name)
        self.assertNotContainsRe(log,
            r"It requested API version")
        self.assertEqual(
            ['wants100'],
            plugin.plugin_warnings.keys())
        self.assertContainsRe(
            plugin.plugin_warnings['wants100'][0],
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


class TestPlugins(BaseTestPlugins):

    def setup_plugin(self, source=""):
        # This test tests a new plugin appears in bzrlib.plugin.plugins().
        # check the plugin is not loaded already
        self.assertPluginUnknown('plugin')
        # write a plugin that _cannot_ fail to load.
        with file('plugin.py', 'w') as f: f.write(source + '\n')
        self.addCleanup(self.teardown_plugin)
        plugin.load_from_path(['.'])

    def teardown_plugin(self):
        self._unregister_plugin('plugin')
        self.assertPluginUnknown('plugin')

    def test_plugin_appears_in_plugins(self):
        self.setup_plugin()
        self.assertPluginKnown('plugin')
        p = plugin.plugins()['plugin']
        self.assertIsInstance(p, bzrlib.plugin.PlugIn)
        self.assertEqual(p.module, plugins.plugin)

    def test_trivial_plugin_get_path(self):
        self.setup_plugin()
        p = plugin.plugins()['plugin']
        plugin_path = self.test_dir + '/plugin.py'
        self.assertIsSameRealPath(plugin_path, osutils.normpath(p.path()))

    def test_plugin_get_path_py_not_pyc(self):
        # first import creates plugin.pyc
        self.setup_plugin()
        self.teardown_plugin()
        plugin.load_from_path(['.']) # import plugin.pyc
        p = plugin.plugins()['plugin']
        plugin_path = self.test_dir + '/plugin.py'
        self.assertIsSameRealPath(plugin_path, osutils.normpath(p.path()))

    def test_plugin_get_path_pyc_only(self):
        # first import creates plugin.pyc (or plugin.pyo depending on __debug__)
        self.setup_plugin()
        self.teardown_plugin()
        os.unlink(self.test_dir + '/plugin.py')
        plugin.load_from_path(['.']) # import plugin.pyc (or .pyo)
        p = plugin.plugins()['plugin']
        if __debug__:
            plugin_path = self.test_dir + '/plugin.pyc'
        else:
            plugin_path = self.test_dir + '/plugin.pyo'
        self.assertIsSameRealPath(plugin_path, osutils.normpath(p.path()))

    def test_no_test_suite_gives_None_for_test_suite(self):
        self.setup_plugin()
        p = plugin.plugins()['plugin']
        self.assertEqual(None, p.test_suite())

    def test_test_suite_gives_test_suite_result(self):
        source = """def test_suite(): return 'foo'"""
        self.setup_plugin(source)
        p = plugin.plugins()['plugin']
        self.assertEqual('foo', p.test_suite())

    def test_no_load_plugin_tests_gives_None_for_load_plugin_tests(self):
        self.setup_plugin()
        loader = tests.TestUtil.TestLoader()
        p = plugin.plugins()['plugin']
        self.assertEqual(None, p.load_plugin_tests(loader))

    def test_load_plugin_tests_gives_load_plugin_tests_result(self):
        source = """
def load_tests(standard_tests, module, loader):
    return 'foo'"""
        self.setup_plugin(source)
        loader = tests.TestUtil.TestLoader()
        p = plugin.plugins()['plugin']
        self.assertEqual('foo', p.load_plugin_tests(loader))

    def check_version_info(self, expected, source='', name='plugin'):
        self.setup_plugin(source)
        self.assertEqual(expected, plugin.plugins()[name].version_info())

    def test_no_version_info(self):
        self.check_version_info(None)

    def test_with_version_info(self):
        self.check_version_info((1, 2, 3, 'dev', 4),
                                "version_info = (1, 2, 3, 'dev', 4)")

    def test_short_version_info_gets_padded(self):
        # the gtk plugin has version_info = (1,2,3) rather than the 5-tuple.
        # so we adapt it
        self.check_version_info((1, 2, 3, 'final', 0),
                                "version_info = (1, 2, 3)")

    def check_version(self, expected, source=None, name='plugin'):
        self.setup_plugin(source)
        self.assertEqual(expected, plugins[name].__version__)

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
        self.assertEqual("1.2.3.2", plugin.__version__)


class TestPluginHelp(tests.TestCaseInTempDir):

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
        f = open(osutils.pathjoin('plugin_test', 'myplug.py'), 'w')
        f.write("""\
from bzrlib import commands
class cmd_myplug(commands.Command):
    __doc__ = '''Just a simple test plugin.'''
    aliases = ['mplg']
    def run(self):
        print 'Hello from my plugin'

"""
)
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
        self.assertEqual("two lines of help\nand more\n\n:See also: bar, foo\n",
                         topic.get_help_text(['foo', 'bar']))

    def test_get_help_topic(self):
        """The help topic for a plugin is its module name."""
        mod = FakeModule('two lines of help\nand more', 'bzrlib.plugins.demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual('demo', topic.get_help_topic())
        mod = FakeModule('two lines of help\nand more',
                         'bzrlib.plugins.foo_bar')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual('foo_bar', topic.get_help_topic())


class TestLoadFromPath(tests.TestCaseInTempDir):

    def setUp(self):
        super(TestLoadFromPath, self).setUp()
        # Change bzrlib.plugin to think no plugins have been loaded yet.
        self.overrideAttr(bzrlib.plugins, '__path__', [])
        self.overrideAttr(plugin, '_loaded', False)

        # Monkey-patch load_from_path to stop it from actually loading anything.
        self.overrideAttr(plugin, 'load_from_path', lambda dirs: None)

    def test_set_plugins_path_with_args(self):
        plugin.set_plugins_path(['a', 'b'])
        self.assertEqual(['a', 'b'], bzrlib.plugins.__path__)

    def test_set_plugins_path_defaults(self):
        plugin.set_plugins_path()
        self.assertEqual(plugin.get_standard_plugins_path(),
                         bzrlib.plugins.__path__)

    def test_get_standard_plugins_path(self):
        path = plugin.get_standard_plugins_path()
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
        self.overrideEnv('BZR_PLUGIN_PATH', 'foo/')
        path = plugin.get_standard_plugins_path()
        for directory in path:
            self.assertNotContainsRe(directory, r'\\/$')

    def test_load_plugins(self):
        plugin.load_plugins(['.'])
        self.assertEqual(bzrlib.plugins.__path__, ['.'])
        # subsequent loads are no-ops
        plugin.load_plugins(['foo'])
        self.assertEqual(bzrlib.plugins.__path__, ['.'])

    def test_load_plugins_default(self):
        plugin.load_plugins()
        path = plugin.get_standard_plugins_path()
        self.assertEqual(path, bzrlib.plugins.__path__)


class TestEnvPluginPath(tests.TestCase):

    def setUp(self):
        super(TestEnvPluginPath, self).setUp()
        self.overrideAttr(plugin, 'DEFAULT_PLUGIN_PATH', None)

        self.user = plugin.get_user_plugin_path()
        self.site = plugin.get_site_plugin_path()
        self.core = plugin.get_core_plugin_path()

    def _list2paths(self, *args):
        paths = []
        for p in args:
            plugin._append_new_path(paths, p)
        return paths

    def _set_path(self, *args):
        path = os.pathsep.join(self._list2paths(*args))
        self.overrideEnv('BZR_PLUGIN_PATH', path)

    def check_path(self, expected_dirs, setting_dirs):
        if setting_dirs:
            self._set_path(*setting_dirs)
        actual = plugin.get_standard_plugins_path()
        self.assertEqual(self._list2paths(*expected_dirs), actual)

    def test_default(self):
        self.check_path([self.user, self.core, self.site],
                        None)

    def test_adhoc_policy(self):
        self.check_path([self.user, self.core, self.site],
                        ['+user', '+core', '+site'])

    def test_fallback_policy(self):
        self.check_path([self.core, self.site, self.user],
                        ['+core', '+site', '+user'])

    def test_override_policy(self):
        self.check_path([self.user, self.site, self.core],
                        ['+user', '+site', '+core'])

    def test_disable_user(self):
        self.check_path([self.core, self.site], ['-user'])

    def test_disable_user_twice(self):
        # Ensures multiple removals don't left cruft
        self.check_path([self.core, self.site], ['-user', '-user'])

    def test_duplicates_are_removed(self):
        self.check_path([self.user, self.core, self.site],
                        ['+user', '+user'])
        # And only the first reference is kept (since the later references will
        # only produce '<plugin> already loaded' mutters)
        self.check_path([self.user, self.core, self.site],
                        ['+user', '+user', '+core',
                         '+user', '+site', '+site',
                         '+core'])

    def test_disable_overrides_enable(self):
        self.check_path([self.core, self.site], ['-user', '+user'])

    def test_disable_core(self):
        self.check_path([self.site], ['-core'])
        self.check_path([self.user, self.site], ['+user', '-core'])

    def test_disable_site(self):
        self.check_path([self.core], ['-site'])
        self.check_path([self.user, self.core], ['-site', '+user'])

    def test_override_site(self):
        self.check_path(['mysite', self.user, self.core],
                        ['mysite', '-site', '+user'])
        self.check_path(['mysite', self.core],
                        ['mysite', '-site'])

    def test_override_core(self):
        self.check_path(['mycore', self.user, self.site],
                        ['mycore', '-core', '+user', '+site'])
        self.check_path(['mycore', self.site],
                        ['mycore', '-core'])

    def test_my_plugin_only(self):
        self.check_path(['myplugin'], ['myplugin', '-user', '-core', '-site'])

    def test_my_plugin_first(self):
        self.check_path(['myplugin', self.core, self.site, self.user],
                        ['myplugin', '+core', '+site', '+user'])

    def test_bogus_references(self):
        self.check_path(['+foo', '-bar', self.core, self.site],
                        ['+foo', '-bar'])


class TestDisablePlugin(BaseTestPlugins):

    def setUp(self):
        super(TestDisablePlugin, self).setUp()
        self.create_plugin_package('test_foo')
        # Make sure we don't pollute the plugins namespace
        self.overrideAttr(plugins, '__path__')
        # Be paranoid in case a test fail
        self.addCleanup(self._unregister_plugin, 'test_foo')

    def test_cannot_import(self):
        self.overrideEnv('BZR_DISABLE_PLUGINS', 'test_foo')
        plugin.set_plugins_path(['.'])
        try:
            import bzrlib.plugins.test_foo
        except ImportError:
            pass
        self.assertPluginUnknown('test_foo')

    def test_regular_load(self):
        self.overrideAttr(plugin, '_loaded', False)
        plugin.load_plugins(['.'])
        self.assertPluginKnown('test_foo')
        self.assertDocstring("This is the doc for test_foo",
                             bzrlib.plugins.test_foo)

    def test_not_loaded(self):
        self.warnings = []
        def captured_warning(*args, **kwargs):
            self.warnings.append((args, kwargs))
        self.overrideAttr(trace, 'warning', captured_warning)
        # Reset the flag that protect against double loading
        self.overrideAttr(plugin, '_loaded', False)
        self.overrideEnv('BZR_DISABLE_PLUGINS', 'test_foo')
        plugin.load_plugins(['.'])
        self.assertPluginUnknown('test_foo')
        # Make sure we don't warn about the plugin ImportError since this has
        # been *requested* by the user.
        self.assertLength(0, self.warnings)



class TestLoadPluginAtSyntax(tests.TestCase):

    def _get_paths(self, paths):
        return plugin._get_specific_plugin_paths(paths)

    def test_empty(self):
        self.assertEqual([], self._get_paths(None))
        self.assertEqual([], self._get_paths(''))

    def test_one_path(self):
        self.assertEqual([('b', 'man')], self._get_paths('b@man'))

    def test_bogus_path(self):
        # We need a '@'
        self.assertRaises(errors.BzrCommandError, self._get_paths, 'batman')
        # Too much '@' isn't good either
        self.assertRaises(errors.BzrCommandError, self._get_paths,
                          'batman@mobile@cave')
        # An empty description probably indicates a problem
        self.assertRaises(errors.BzrCommandError, self._get_paths,
                          os.pathsep.join(['batman@cave', '', 'robin@mobile']))


class TestLoadPluginAt(BaseTestPlugins):

    def setUp(self):
        super(TestLoadPluginAt, self).setUp()
        # Make sure we don't pollute the plugins namespace
        self.overrideAttr(plugins, '__path__')
        # Reset the flag that protect against double loading
        self.overrideAttr(plugin, '_loaded', False)
        # Create the same plugin in two directories
        self.create_plugin_package('test_foo', dir='non-standard-dir')
        # The "normal" directory, we use 'standard' instead of 'plugins' to
        # avoid depending on the precise naming.
        self.create_plugin_package('test_foo', dir='standard/test_foo')
        # All the tests will load the 'test_foo' plugin from various locations
        self.addCleanup(self._unregister_plugin, 'test_foo')
        # Unfortunately there's global cached state for the specific
        # registered paths.
        self.addCleanup(plugin.PluginImporter.reset)

    def assertTestFooLoadedFrom(self, path):
        self.assertPluginKnown('test_foo')
        self.assertDocstring('This is the doc for test_foo',
                             bzrlib.plugins.test_foo)
        self.assertEqual(path, bzrlib.plugins.test_foo.dir_source)

    def test_regular_load(self):
        plugin.load_plugins(['standard'])
        self.assertTestFooLoadedFrom('standard/test_foo')

    def test_import(self):
        self.overrideEnv('BZR_PLUGINS_AT', 'test_foo@non-standard-dir')
        plugin.set_plugins_path(['standard'])
        try:
            import bzrlib.plugins.test_foo
        except ImportError:
            pass
        self.assertTestFooLoadedFrom('non-standard-dir')

    def test_loading(self):
        self.overrideEnv('BZR_PLUGINS_AT', 'test_foo@non-standard-dir')
        plugin.load_plugins(['standard'])
        self.assertTestFooLoadedFrom('non-standard-dir')

    def test_compiled_loaded(self):
        self.overrideEnv('BZR_PLUGINS_AT', 'test_foo@non-standard-dir')
        plugin.load_plugins(['standard'])
        self.assertTestFooLoadedFrom('non-standard-dir')
        self.assertIsSameRealPath('non-standard-dir/__init__.py',
                                  bzrlib.plugins.test_foo.__file__)

        # Try importing again now that the source has been compiled
        self._unregister_plugin('test_foo')
        plugin._loaded = False
        plugin.load_plugins(['standard'])
        self.assertTestFooLoadedFrom('non-standard-dir')
        if __debug__:
            suffix = 'pyc'
        else:
            suffix = 'pyo'
        self.assertIsSameRealPath('non-standard-dir/__init__.%s' % suffix,
                                  bzrlib.plugins.test_foo.__file__)

    def test_submodule_loading(self):
        # We create an additional directory under the one for test_foo
        self.create_plugin_package('test_bar', dir='non-standard-dir/test_bar')
        self.addCleanup(self._unregister_plugin_submodule,
                        'test_foo', 'test_bar')
        self.overrideEnv('BZR_PLUGINS_AT', 'test_foo@non-standard-dir')
        plugin.set_plugins_path(['standard'])
        import bzrlib.plugins.test_foo
        self.assertEqual('bzrlib.plugins.test_foo',
                         bzrlib.plugins.test_foo.__package__)
        import bzrlib.plugins.test_foo.test_bar
        self.assertIsSameRealPath('non-standard-dir/test_bar/__init__.py',
                                  bzrlib.plugins.test_foo.test_bar.__file__)

    def test_relative_submodule_loading(self):
        self.create_plugin_package('test_foo', dir='another-dir', source='''
import test_bar
''')
        # We create an additional directory under the one for test_foo
        self.create_plugin_package('test_bar', dir='another-dir/test_bar')
        self.addCleanup(self._unregister_plugin_submodule,
                        'test_foo', 'test_bar')
        self.overrideEnv('BZR_PLUGINS_AT', 'test_foo@another-dir')
        plugin.set_plugins_path(['standard'])
        import bzrlib.plugins.test_foo
        self.assertEqual('bzrlib.plugins.test_foo',
                         bzrlib.plugins.test_foo.__package__)
        self.assertIsSameRealPath('another-dir/test_bar/__init__.py',
                                  bzrlib.plugins.test_foo.test_bar.__file__)

    def test_loading_from___init__only(self):
        # We rename the existing __init__.py file to ensure that we don't load
        # a random file
        init = 'non-standard-dir/__init__.py'
        random = 'non-standard-dir/setup.py'
        os.rename(init, random)
        self.addCleanup(os.rename, random, init)
        self.overrideEnv('BZR_PLUGINS_AT', 'test_foo@non-standard-dir')
        plugin.load_plugins(['standard'])
        self.assertPluginUnknown('test_foo')

    def test_loading_from_specific_file(self):
        plugin_dir = 'non-standard-dir'
        plugin_file_name = 'iamtestfoo.py'
        plugin_path = osutils.pathjoin(plugin_dir, plugin_file_name)
        source = '''\
"""This is the doc for %s"""
dir_source = '%s'
''' % ('test_foo', plugin_path)
        self.create_plugin('test_foo', source=source,
                           dir=plugin_dir, file_name=plugin_file_name)
        self.overrideEnv('BZR_PLUGINS_AT', 'test_foo@%s' % plugin_path)
        plugin.load_plugins(['standard'])
        self.assertTestFooLoadedFrom(plugin_path)


class TestDescribePlugins(BaseTestPlugins):

    def test_describe_plugins(self):
        class DummyModule(object):
            __doc__ = 'Hi there'
        class DummyPlugin(object):
            __version__ = '0.1.0'
            module = DummyModule()
        def dummy_plugins():
            return { 'good': DummyPlugin() }
        self.overrideAttr(plugin, 'plugin_warnings',
            {'bad': ['Failed to load (just testing)']})
        self.overrideAttr(plugin, 'plugins', dummy_plugins)
        self.assertEqual("""\
bad (failed to load)
  ** Failed to load (just testing)

good 0.1.0
  Hi there

""", ''.join(plugin.describe_plugins()))
