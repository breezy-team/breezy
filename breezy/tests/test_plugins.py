# Copyright (C) 2005-2012, 2016 Canonical Ltd
# Copyright (C) 2017-2018 Breezy developers
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

"""Tests for plugins."""

import importlib
import logging
import os
import sys
import types
from io import StringIO
from typing import Any

import breezy

from .. import osutils, plugin, tests

# TODO: Write a test for plugin decoration of commands.

invalidate_caches = getattr(importlib, "invalidate_caches", lambda: None)


class BaseTestPlugins(tests.TestCaseInTempDir):
    """TestCase that isolates plugin imports and cleans up on completion."""

    def setUp(self):
        super().setUp()
        self.module_name = "breezy.testingplugins"
        self.module_prefix = self.module_name + "."
        self.module = types.ModuleType(self.module_name)

        self.overrideAttr(plugin, "_MODULE_PREFIX", self.module_prefix)
        self.overrideAttr(breezy, "testingplugins", self.module)

        sys.modules[self.module_name] = self.module
        self.addCleanup(self._unregister_all)
        self.addCleanup(self._unregister_finder)

        invalidate_caches()

    def reset(self):
        """Remove all global testing state and clean up module."""
        # GZ 2017-06-02: Ideally don't do this, write new test or generate
        # bytecode by other mechanism.
        self.log("resetting plugin testing context")
        self._unregister_all()
        self._unregister_finder()
        sys.modules[self.module_name] = self.module
        for name in list(self.module.__dict__):
            if name[:2] != "__":
                delattr(self.module, name)
        invalidate_caches()
        self.plugins = None

    def update_module_paths(self, paths):
        paths = plugin.extend_path(paths, self.module_name)
        self.module.__path__ = paths
        self.log("using %r", paths)
        return paths

    def load_with_paths(self, paths, warn_load_problems=True):
        self.log("loading plugins!")
        plugin.load_plugins(
            self.update_module_paths(paths),
            state=self,
            warn_load_problems=warn_load_problems,
        )

    def create_plugin(self, name, source=None, dir=".", file_name=None):
        if source is None:
            source = '''\
"""This is the doc for {}"""
'''.format(name)
        if file_name is None:
            file_name = name + ".py"
        # 'source' must not fail to load
        path = osutils.pathjoin(dir, file_name)
        with open(path, "w") as f:
            f.write(source + "\n")

    def create_plugin_package(self, name, dir=None, source=None):
        if dir is None:
            dir = name
        if source is None:
            source = '''\
"""This is the doc for {}"""
dir_source = '{}'
'''.format(name, dir)
        os.makedirs(dir)
        self.create_plugin(name, source, dir, file_name="__init__.py")

    def promote_cache(self, directory):
        """Move bytecode files out of __pycache__ in given directory."""
        cache_dir = os.path.join(directory, "__pycache__")
        if os.path.isdir(cache_dir):
            for name in os.listdir(cache_dir):
                magicless_name = ".".join(name.split(".")[0 :: name.count(".")])
                rel = osutils.relpath(self.test_dir, cache_dir)
                self.log("moving %s in %s to %s", name, rel, magicless_name)
                os.rename(
                    os.path.join(cache_dir, name),
                    os.path.join(directory, magicless_name),
                )

    def _unregister_finder(self):
        """Removes any test copies of _PluginsAtFinder from sys.meta_path."""
        idx = len(sys.meta_path)
        while idx:
            idx -= 1
            finder = sys.meta_path[idx]
            if getattr(finder, "prefix", "") == self.module_prefix:
                self.log("removed %r from sys.meta_path", finder)
                sys.meta_path.pop(idx)

    def _unregister_all(self):
        """Remove all plugins in the test namespace from sys.modules."""
        for name in list(sys.modules):
            if name.startswith(self.module_prefix) or name == self.module_name:
                self.log("removed %s from sys.modules", name)
                del sys.modules[name]

    def assertPluginModules(self, plugin_dict):
        self.assertEqual(
            {
                k[len(self.module_prefix) :]: sys.modules[k]
                for k in sys.modules
                if k.startswith(self.module_prefix)
            },
            plugin_dict,
        )

    def assertPluginUnknown(self, name):
        self.assertTrue(getattr(self.module, name, None) is None)
        self.assertFalse(self.module_prefix + name in sys.modules)

    def assertPluginKnown(self, name):
        self.assertTrue(
            getattr(self.module, name, None) is not None,
            "plugins known: {!r}".format(dir(self.module)),
        )
        self.assertTrue(self.module_prefix + name in sys.modules)


class TestLoadingPlugins(BaseTestPlugins):
    activeattributes: dict[str, list[Any]] = {}

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
        self.__class__.activeattributes[tempattribute] = []
        self.assertTrue(tempattribute in self.activeattributes)
        # create two plugin directories
        os.mkdir("first")
        os.mkdir("second")
        # write a plugin that will record when its loaded in the
        # tempattribute list.
        template = (
            "from breezy.tests.test_plugins import TestLoadingPlugins\n"
            "TestLoadingPlugins.activeattributes[%r].append('%s')\n"
        )

        with open(os.path.join("first", "plugin.py"), "w") as outfile:
            outfile.write(template % (tempattribute, "first"))
            outfile.write("\n")

        with open(os.path.join("second", "plugin.py"), "w") as outfile:
            outfile.write(template % (tempattribute, "second"))
            outfile.write("\n")

        try:
            self.load_with_paths(["first", "second"])
            self.assertEqual(["first"], self.activeattributes[tempattribute])
        finally:
            del self.activeattributes[tempattribute]

    def test_plugins_from_different_dirs_can_demand_load(self):
        self.assertFalse("breezy.plugins.pluginone" in sys.modules)
        self.assertFalse("breezy.plugins.plugintwo" in sys.modules)
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
        breezy.tests.test_plugins.TestLoadingPlugins.activeattributes[
            tempattribute
        ] = []
        self.assertTrue(tempattribute in self.activeattributes)
        # create two plugin directories
        os.mkdir("first")
        os.mkdir("second")
        # write plugins that will record when they are loaded in the
        # tempattribute list.
        template = (
            "from breezy.tests.test_plugins import TestLoadingPlugins\n"
            "TestLoadingPlugins.activeattributes[%r].append('%s')\n"
        )

        with open(os.path.join("first", "pluginone.py"), "w") as outfile:
            outfile.write(template % (tempattribute, "first"))
            outfile.write("\n")

        with open(os.path.join("second", "plugintwo.py"), "w") as outfile:
            outfile.write(template % (tempattribute, "second"))
            outfile.write("\n")

        try:
            self.assertPluginUnknown("pluginone")
            self.assertPluginUnknown("plugintwo")
            self.update_module_paths(["first", "second"])
            exec("import {}pluginone".format(self.module_prefix))
            self.assertEqual(["first"], self.activeattributes[tempattribute])
            exec("import {}plugintwo".format(self.module_prefix))
            self.assertEqual(["first", "second"], self.activeattributes[tempattribute])
        finally:
            del self.activeattributes[tempattribute]

    def test_plugins_can_load_from_directory_with_trailing_slash(self):
        # This test tests that a plugin can load from a directory when the
        # directory in the path has a trailing slash.
        # check the plugin is not loaded already
        self.assertPluginUnknown("ts_plugin")
        tempattribute = "trailing-slash"
        self.assertFalse(tempattribute in self.activeattributes)
        # set a place for the plugin to record its loading, and at the same
        # time validate that the location the plugin should record to is
        # valid and correct.
        breezy.tests.test_plugins.TestLoadingPlugins.activeattributes[
            tempattribute
        ] = []
        self.assertTrue(tempattribute in self.activeattributes)
        # create a directory for the plugin
        os.mkdir("plugin_test")
        # write a plugin that will record when its loaded in the
        # tempattribute list.
        template = (
            "from breezy.tests.test_plugins import TestLoadingPlugins\n"
            "TestLoadingPlugins.activeattributes[%r].append('%s')\n"
        )

        with open(os.path.join("plugin_test", "ts_plugin.py"), "w") as outfile:
            outfile.write(template % (tempattribute, "plugin"))
            outfile.write("\n")

        try:
            self.load_with_paths(["plugin_test" + os.sep])
            self.assertEqual(["plugin"], self.activeattributes[tempattribute])
            self.assertPluginKnown("ts_plugin")
        finally:
            del self.activeattributes[tempattribute]

    def load_and_capture(self, name, warn_load_problems=True):
        """Load plugins from '.' capturing the output.

        :param name: The name of the plugin.
        :return: A string with the log from the plugin loading call.
        """
        # Capture output
        stream = StringIO()
        try:
            handler = logging.StreamHandler(stream)
            log = logging.getLogger("brz")
            log.addHandler(handler)
            try:
                self.load_with_paths(["."], warn_load_problems=warn_load_problems)
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

        Observe that it records the problem but doesn't complain on stderr
        when warn_load_problems=False
        """
        name = "wants100.py"
        with open(name, "w") as f:
            f.write(
                "import breezy\n"
                "from breezy.errors import IncompatibleVersion\n"
                "raise IncompatibleVersion(breezy, [(1, 0, 0)], (0, 0, 5))\n"
            )
        log = self.load_and_capture(name, warn_load_problems=False)
        self.assertNotContainsRe(log, r"It supports breezy version")
        self.assertEqual({"wants100"}, self.plugin_warnings.keys())
        self.assertContainsRe(
            self.plugin_warnings["wants100"][0], r"It supports breezy version"
        )

    def test_plugin_with_bad_name_does_not_load(self):
        # The file name here invalid for a python module.
        name = "brz-bad plugin-name..py"
        open(name, "w").close()
        log = self.load_and_capture(name)
        self.assertContainsRe(
            log,
            r"Unable to load 'brz-bad plugin-name\.' in '.*' as a plugin "
            "because the file path isn't a valid module name; try renaming "
            "it to 'bad_plugin_name_'\\.",
        )

    def test_plugin_with_error_suppress(self):
        # The file name here invalid for a python module.
        name = "some_error.py"
        with open(name, "w") as f:
            f.write('raise Exception("bad")\n')
        log = self.load_and_capture(name, warn_load_problems=False)
        self.assertEqual("", log)

    def test_plugin_with_error(self):
        # The file name here invalid for a python module.
        name = "some_error.py"
        with open(name, "w") as f:
            f.write('raise Exception("bad")\n')
        log = self.load_and_capture(name, warn_load_problems=True)
        self.assertContainsRe(
            log, "Unable to load plugin 'some_error' from '.*': bad\n"
        )


class TestPlugins(BaseTestPlugins):
    def setup_plugin(self, source=""):
        # This test tests a new plugin appears in breezy.plugin.plugins().
        # check the plugin is not loaded already
        self.assertPluginUnknown("plugin")
        # write a plugin that _cannot_ fail to load.
        with open("plugin.py", "w") as f:
            f.write(source + "\n")
        self.load_with_paths(["."])

    def test_plugin_loaded(self):
        self.assertPluginUnknown("plugin")
        self.assertIs(None, breezy.plugin.get_loaded_plugin("plugin"))
        self.setup_plugin()
        p = breezy.plugin.get_loaded_plugin("plugin")
        self.assertIsInstance(p, breezy.plugin.PlugIn)
        self.assertIs(p.module, sys.modules[self.module_prefix + "plugin"])

    def test_plugin_loaded_disabled(self):
        self.assertPluginUnknown("plugin")
        self.overrideEnv("BRZ_DISABLE_PLUGINS", "plugin")
        self.setup_plugin()
        self.assertIs(None, breezy.plugin.get_loaded_plugin("plugin"))

    def test_plugin_appears_in_plugins(self):
        self.setup_plugin()
        self.assertPluginKnown("plugin")
        p = self.plugins["plugin"]
        self.assertIsInstance(p, breezy.plugin.PlugIn)
        self.assertIs(p.module, sys.modules[self.module_prefix + "plugin"])

    def test_trivial_plugin_get_path(self):
        self.setup_plugin()
        p = self.plugins["plugin"]
        plugin_path = self.test_dir + "/plugin.py"
        self.assertIsSameRealPath(plugin_path, osutils.normpath(p.path()))

    def test_plugin_get_path_py_not_pyc(self):
        # first import creates plugin.pyc
        self.setup_plugin()
        self.promote_cache(self.test_dir)
        self.reset()
        self.load_with_paths(["."])  # import plugin.pyc
        p = plugin.plugins()["plugin"]
        plugin_path = self.test_dir + "/plugin.py"
        self.assertIsSameRealPath(plugin_path, osutils.normpath(p.path()))

    def test_plugin_get_path_pyc_only(self):
        # first import creates plugin.pyc (or plugin.pyo depending on __debug__)
        self.setup_plugin()
        os.unlink(self.test_dir + "/plugin.py")
        self.promote_cache(self.test_dir)
        self.reset()
        self.load_with_paths(["."])  # import plugin.pyc (or .pyo)
        p = plugin.plugins()["plugin"]
        plugin_path = self.test_dir + "/plugin" + plugin.COMPILED_EXT
        self.assertIsSameRealPath(plugin_path, osutils.normpath(p.path()))

    def test_no_test_suite_gives_None_for_test_suite(self):
        self.setup_plugin()
        p = plugin.plugins()["plugin"]
        self.assertEqual(None, p.test_suite())

    def test_test_suite_gives_test_suite_result(self):
        source = """def test_suite(): return 'foo'"""
        self.setup_plugin(source)
        p = plugin.plugins()["plugin"]
        self.assertEqual("foo", p.test_suite())

    def test_no_load_plugin_tests_gives_None_for_load_plugin_tests(self):
        self.setup_plugin()
        loader = tests.TestUtil.TestLoader()
        p = plugin.plugins()["plugin"]
        self.assertEqual(None, p.load_plugin_tests(loader))

    def test_load_plugin_tests_gives_load_plugin_tests_result(self):
        source = """
def load_tests(loader, standard_tests, pattern):
    return 'foo'"""
        self.setup_plugin(source)
        loader = tests.TestUtil.TestLoader()
        p = plugin.plugins()["plugin"]
        self.assertEqual("foo", p.load_plugin_tests(loader))

    def check_version_info(self, expected, source="", name="plugin"):
        self.setup_plugin(source)
        self.assertEqual(expected, plugin.plugins()[name].version_info())

    def test_no_version_info(self):
        self.check_version_info(None)

    def test_with_version_info(self):
        self.check_version_info(
            (1, 2, 3, "dev", 4), "version_info = (1, 2, 3, 'dev', 4)"
        )

    def test_short_version_info_gets_padded(self):
        # the gtk plugin has version_info = (1,2,3) rather than the 5-tuple.
        # so we adapt it
        self.check_version_info((1, 2, 3, "final", 0), "version_info = (1, 2, 3)")

    def check_version(self, expected, source=None, name="plugin"):
        self.setup_plugin(source)
        self.assertEqual(expected, plugins[name].__version__)

    def test_no_version_info___version__(self):
        self.setup_plugin()
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("unknown", plugin.__version__)

    def test_str__version__with_version_info(self):
        self.setup_plugin("version_info = '1.2.3'")
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("1.2.3", plugin.__version__)

    def test_noniterable__version__with_version_info(self):
        self.setup_plugin("version_info = (1)")
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("1", plugin.__version__)

    def test_1__version__with_version_info(self):
        self.setup_plugin("version_info = (1,)")
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("1", plugin.__version__)

    def test_1_2__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2)")
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("1.2", plugin.__version__)

    def test_1_2_3__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3)")
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("1.2.3", plugin.__version__)

    def test_candidate__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'candidate', 1)")
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("1.2.3.rc1", plugin.__version__)

    def test_dev__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'dev', 0)")
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("1.2.3.dev", plugin.__version__)

    def test_dev_fallback__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'dev', 4)")
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("1.2.3.dev4", plugin.__version__)

    def test_final__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'final', 0)")
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("1.2.3", plugin.__version__)

    def test_final_fallback__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'final', 2)")
        plugin = breezy.plugin.plugins()["plugin"]
        self.assertEqual("1.2.3.2", plugin.__version__)


class TestHelpIndex(tests.TestCase):
    """Tests for the PluginsHelpIndex class."""

    def test_default_constructable(self):
        plugin.PluginsHelpIndex()

    def test_get_topics_None(self):
        """Searching for None returns an empty list."""
        index = plugin.PluginsHelpIndex()
        self.assertEqual([], index.get_topics(None))

    def test_get_topics_for_plugin(self):
        """Searching for plugin name gets its docstring."""
        index = plugin.PluginsHelpIndex()
        # make a new plugin here for this test, even if we're run with
        # --no-plugins
        self.assertFalse("breezy.plugins.demo_module" in sys.modules)
        demo_module = FakeModule("", "breezy.plugins.demo_module")
        sys.modules["breezy.plugins.demo_module"] = demo_module
        try:
            topics = index.get_topics("demo_module")
            self.assertEqual(1, len(topics))
            self.assertIsInstance(topics[0], plugin.ModuleHelpTopic)
            self.assertEqual(demo_module, topics[0].module)
        finally:
            del sys.modules["breezy.plugins.demo_module"]

    def test_get_topics_no_topic(self):
        """Searching for something that is not a plugin returns []."""
        # test this by using a name that cannot be a plugin - its not
        # a valid python identifier.
        index = plugin.PluginsHelpIndex()
        self.assertEqual([], index.get_topics("nothing by this name"))

    def test_prefix(self):
        """PluginsHelpIndex has a prefix of 'plugins/'."""
        index = plugin.PluginsHelpIndex()
        self.assertEqual("plugins/", index.prefix)

    def test_get_plugin_topic_with_prefix(self):
        """Searching for plugins/demo_module returns help."""
        index = plugin.PluginsHelpIndex()
        self.assertFalse("breezy.plugins.demo_module" in sys.modules)
        demo_module = FakeModule("", "breezy.plugins.demo_module")
        sys.modules["breezy.plugins.demo_module"] = demo_module
        try:
            topics = index.get_topics("plugins/demo_module")
            self.assertEqual(1, len(topics))
            self.assertIsInstance(topics[0], plugin.ModuleHelpTopic)
            self.assertEqual(demo_module, topics[0].module)
        finally:
            del sys.modules["breezy.plugins.demo_module"]


class FakeModule:
    """A fake module to test with."""

    def __init__(self, doc, name):
        self.__doc__ = doc
        self.__name__ = name


class TestModuleHelpTopic(tests.TestCase):
    """Tests for the ModuleHelpTopic class."""

    def test_contruct(self):
        """Construction takes the module to document."""
        mod = FakeModule("foo", "foo")
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual(mod, topic.module)

    def test_get_help_text_None(self):
        """A ModuleHelpTopic returns the docstring for get_help_text."""
        mod = FakeModule(None, "demo")
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("Plugin 'demo' has no docstring.\n", topic.get_help_text())

    def test_get_help_text_no_carriage_return(self):
        r"""ModuleHelpTopic.get_help_text adds a \n if needed."""
        mod = FakeModule("one line of help", "demo")
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("one line of help\n", topic.get_help_text())

    def test_get_help_text_carriage_return(self):
        r"""ModuleHelpTopic.get_help_text adds a \n if needed."""
        mod = FakeModule("two lines of help\nand more\n", "demo")
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("two lines of help\nand more\n", topic.get_help_text())

    def test_get_help_text_with_additional_see_also(self):
        mod = FakeModule("two lines of help\nand more", "demo")
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual(
            "two lines of help\nand more\n\n:See also: bar, foo\n",
            topic.get_help_text(["foo", "bar"]),
        )

    def test_get_help_topic(self):
        """The help topic for a plugin is its module name."""
        mod = FakeModule("two lines of help\nand more", "breezy.plugins.demo")
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("demo", topic.get_help_topic())
        mod = FakeModule("two lines of help\nand more", "breezy.plugins.foo_bar")
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("foo_bar", topic.get_help_topic())


class TestEnvPluginPath(tests.TestCase):
    user = "USER"
    core = "CORE"
    site = "SITE"

    def check_path(self, expected_dirs, setting_dirs):
        if setting_dirs is None:
            del os.environ["BRZ_PLUGIN_PATH"]
        else:
            os.environ["BRZ_PLUGIN_PATH"] = os.pathsep.join(setting_dirs)
        actual = [
            (p if t == "path" else t.upper()) for p, t in plugin._env_plugin_path()
        ]
        self.assertEqual(expected_dirs, actual)

    def test_default(self):
        self.check_path([self.user, self.core, self.site], None)

    def test_adhoc_policy(self):
        self.check_path([self.user, self.core, self.site], ["+user", "+core", "+site"])

    def test_fallback_policy(self):
        self.check_path([self.core, self.site, self.user], ["+core", "+site", "+user"])

    def test_override_policy(self):
        self.check_path([self.user, self.site, self.core], ["+user", "+site", "+core"])

    def test_disable_user(self):
        self.check_path([self.core, self.site], ["-user"])

    def test_disable_user_twice(self):
        # Ensures multiple removals don't left cruft
        self.check_path([self.core, self.site], ["-user", "-user"])

    def test_duplicates_are_removed(self):
        self.check_path([self.user, self.core, self.site], ["+user", "+user"])
        # And only the first reference is kept (since the later references will
        # only produce '<plugin> already loaded' mutters)
        self.check_path(
            [self.user, self.core, self.site],
            ["+user", "+user", "+core", "+user", "+site", "+site", "+core"],
        )

    def test_disable_overrides_enable(self):
        self.check_path([self.core, self.site], ["-user", "+user"])

    def test_disable_core(self):
        self.check_path([self.site], ["-core"])
        self.check_path([self.user, self.site], ["+user", "-core"])

    def test_disable_site(self):
        self.check_path([self.core], ["-site"])
        self.check_path([self.user, self.core], ["-site", "+user"])

    def test_override_site(self):
        self.check_path(["mysite", self.user, self.core], ["mysite", "-site", "+user"])
        self.check_path(["mysite", self.core], ["mysite", "-site"])

    def test_override_core(self):
        self.check_path(
            ["mycore", self.user, self.site], ["mycore", "-core", "+user", "+site"]
        )
        self.check_path(["mycore", self.site], ["mycore", "-core"])

    def test_my_plugin_only(self):
        self.check_path(["myplugin"], ["myplugin", "-user", "-core", "-site"])

    def test_my_plugin_first(self):
        self.check_path(
            ["myplugin", self.core, self.site, self.user],
            ["myplugin", "+core", "+site", "+user"],
        )

    def test_bogus_references(self):
        self.check_path(["+foo", "-bar", self.core, self.site], ["+foo", "-bar"])


class TestDisablePlugin(BaseTestPlugins):
    def test_cannot_import(self):
        self.create_plugin_package("works")
        self.create_plugin_package("fails")
        self.overrideEnv("BRZ_DISABLE_PLUGINS", "fails")
        self.update_module_paths(["."])
        import breezy.testingplugins.works as works

        try:
            import breezy.testingplugins.fails as fails
        except ImportError:
            pass
        else:
            self.fail("Loaded blocked plugin: " + repr(fails))
        self.assertPluginModules({"fails": None, "works": works})

    def test_partial_imports(self):
        self.create_plugin("good")
        self.create_plugin("bad")
        self.create_plugin_package("ugly")
        self.overrideEnv("BRZ_DISABLE_PLUGINS", "bad:ugly")
        self.load_with_paths(["."])
        self.assertEqual({"good"}, self.plugins.keys())
        self.assertPluginModules(
            {
                "good": self.plugins["good"].module,
                "bad": None,
                "ugly": None,
            }
        )
        # Ensure there are no warnings about plugins not being imported as
        # the user has explictly requested they be disabled.
        self.assertNotContainsRe(self.get_log(), r"Unable to load plugin")


class TestEnvDisablePlugins(tests.TestCase):
    def _get_names(self, env_value):
        os.environ["BRZ_DISABLE_PLUGINS"] = env_value
        return plugin._env_disable_plugins()

    def test_unset(self):
        self.assertEqual([], plugin._env_disable_plugins())

    def test_empty(self):
        self.assertEqual([], self._get_names(""))

    def test_single(self):
        self.assertEqual(["single"], self._get_names("single"))

    def test_multi(self):
        expected = ["one", "two"]
        self.assertEqual(expected, self._get_names(os.pathsep.join(expected)))

    def test_mixed(self):
        value = os.pathsep.join(["valid", "in-valid"])
        self.assertEqual(["valid"], self._get_names(value))
        self.assertContainsRe(
            self.get_log(),
            r"Invalid name 'in-valid' in BRZ_DISABLE_PLUGINS=" + repr(value),
        )


class TestEnvPluginsAt(tests.TestCase):
    def _get_paths(self, env_value):
        os.environ["BRZ_PLUGINS_AT"] = env_value
        return plugin._env_plugins_at()

    def test_empty(self):
        self.assertEqual([], plugin._env_plugins_at())
        self.assertEqual([], self._get_paths(""))

    def test_one_path(self):
        self.assertEqual([("b", os.path.abspath("man"))], self._get_paths("b@man"))

    def test_multiple(self):
        self.assertEqual(
            [
                ("tools", os.path.abspath("bzr-tools")),
                ("p", os.path.abspath("play.py")),
            ],
            self._get_paths(os.pathsep.join(("tools@bzr-tools", "p@play.py"))),
        )

    def test_many_at(self):
        self.assertEqual(
            [("church", os.path.abspath("StMichael@Plea@Norwich"))],
            self._get_paths("church@StMichael@Plea@Norwich"),
        )

    def test_only_py(self):
        self.assertEqual(
            [("test", os.path.abspath("test.py"))], self._get_paths("./test.py")
        )

    def test_only_package(self):
        self.assertEqual([("py", "/opt/b/py")], self._get_paths("/opt/b/py"))

    def test_bad_name(self):
        self.assertEqual([], self._get_paths("/usr/local/bzr-git"))
        self.assertContainsRe(
            self.get_log(),
            r"Invalid name 'bzr-git' in BRZ_PLUGINS_AT='/usr/local/bzr-git'",
        )


class TestLoadPluginAt(BaseTestPlugins):
    def setUp(self):
        super().setUp()
        # Create the same plugin in two directories
        self.create_plugin_package("test_foo", dir="non-standard-dir")
        # The "normal" directory, we use 'standard' instead of 'plugins' to
        # avoid depending on the precise naming.
        self.create_plugin_package("test_foo", dir="standard/test_foo")

    def assertTestFooLoadedFrom(self, path):
        self.assertPluginKnown("test_foo")
        self.assertDocstring("This is the doc for test_foo", self.module.test_foo)
        self.assertEqual(path, self.module.test_foo.dir_source)

    def test_regular_load(self):
        self.load_with_paths(["standard"])
        self.assertTestFooLoadedFrom("standard/test_foo")

    def test_import(self):
        self.overrideEnv("BRZ_PLUGINS_AT", "test_foo@non-standard-dir")
        self.update_module_paths(["standard"])
        import breezy.testingplugins.test_foo  # noqa: F401

        self.assertTestFooLoadedFrom("non-standard-dir")

    def test_loading(self):
        self.overrideEnv("BRZ_PLUGINS_AT", "test_foo@non-standard-dir")
        self.load_with_paths(["standard"])
        self.assertTestFooLoadedFrom("non-standard-dir")

    def test_loading_other_name(self):
        self.overrideEnv("BRZ_PLUGINS_AT", "test_foo@non-standard-dir")
        os.rename("standard/test_foo", "standard/test_bar")
        self.load_with_paths(["standard"])
        self.assertTestFooLoadedFrom("non-standard-dir")

    def test_compiled_loaded(self):
        self.overrideEnv("BRZ_PLUGINS_AT", "test_foo@non-standard-dir")
        self.load_with_paths(["standard"])
        self.assertTestFooLoadedFrom("non-standard-dir")
        self.assertIsSameRealPath(
            "non-standard-dir/__init__.py", self.module.test_foo.__file__
        )

        # Try importing again now that the source has been compiled
        os.remove("non-standard-dir/__init__.py")
        self.promote_cache("non-standard-dir")
        self.reset()
        self.load_with_paths(["standard"])
        self.assertTestFooLoadedFrom("non-standard-dir")
        suffix = plugin.COMPILED_EXT
        self.assertIsSameRealPath(
            "non-standard-dir/__init__" + suffix, self.module.test_foo.__file__
        )

    def test_submodule_loading(self):
        # We create an additional directory under the one for test_foo
        self.create_plugin_package("test_bar", dir="non-standard-dir/test_bar")
        self.overrideEnv("BRZ_PLUGINS_AT", "test_foo@non-standard-dir")
        self.update_module_paths(["standard"])
        import breezy.testingplugins.test_foo

        self.assertEqual(
            self.module_prefix + "test_foo", self.module.test_foo.__package__
        )
        import breezy.testingplugins.test_foo.test_bar  # noqa: F401

        self.assertIsSameRealPath(
            "non-standard-dir/test_bar/__init__.py",
            self.module.test_foo.test_bar.__file__,
        )

    def test_relative_submodule_loading(self):
        self.create_plugin_package(
            "test_foo",
            dir="another-dir",
            source="""
from . import test_bar
""",
        )
        # We create an additional directory under the one for test_foo
        self.create_plugin_package("test_bar", dir="another-dir/test_bar")
        self.overrideEnv("BRZ_PLUGINS_AT", "test_foo@another-dir")
        self.update_module_paths(["standard"])
        import breezy.testingplugins.test_foo  # noqa: F401

        self.assertEqual(
            self.module_prefix + "test_foo", self.module.test_foo.__package__
        )
        self.assertIsSameRealPath(
            "another-dir/test_bar/__init__.py", self.module.test_foo.test_bar.__file__
        )

    def test_loading_from___init__only(self):
        # We rename the existing __init__.py file to ensure that we don't load
        # a random file
        init = "non-standard-dir/__init__.py"
        random = "non-standard-dir/setup.py"
        os.rename(init, random)
        self.overrideEnv("BRZ_PLUGINS_AT", "test_foo@non-standard-dir")
        self.load_with_paths(["standard"])
        self.assertPluginUnknown("test_foo")

    def test_loading_from_specific_file(self):
        plugin_dir = "non-standard-dir"
        plugin_file_name = "iamtestfoo.py"
        plugin_path = osutils.pathjoin(plugin_dir, plugin_file_name)
        source = '''\
"""This is the doc for {}"""
dir_source = '{}'
'''.format("test_foo", plugin_path)
        self.create_plugin(
            "test_foo", source=source, dir=plugin_dir, file_name=plugin_file_name
        )
        self.overrideEnv("BRZ_PLUGINS_AT", "test_foo@{}".format(plugin_path))
        self.load_with_paths(["standard"])
        self.assertTestFooLoadedFrom(plugin_path)


class TestDescribePlugins(BaseTestPlugins):
    def test_describe_plugins(self):
        class DummyModule:
            __doc__ = "Hi there"

        class DummyPlugin:
            __version__ = "0.1.0"
            module = DummyModule()

        self.plugin_warnings = {"bad": ["Failed to load (just testing)"]}
        self.plugins = {"good": DummyPlugin()}
        self.assertEqual(
            """\
bad (failed to load)
  ** Failed to load (just testing)

good 0.1.0
  Hi there

""",
            "".join(plugin.describe_plugins(state=self)),
        )
