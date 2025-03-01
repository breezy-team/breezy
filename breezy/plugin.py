# Copyright (C) 2005-2011 Canonical Ltd, 2017 Breezy developers
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

__docformat__ = "google"

"""Breezy plugin support.

Which plugins to load can be configured by setting these environment variables:

- BRZ_PLUGIN_PATH: Paths to look for plugins in.
- BRZ_DISABLE_PLUGINS: Plugin names to block from being loaded.
- BRZ_PLUGINS_AT: Name and paths for plugins to load from specific locations.

The interfaces this module exports include:

- disable_plugins: Load no plugins and stop future automatic loading.
- load_plugins: Load all plugins that can be found in configuration.
- describe_plugins: Generate text for each loaded (or failed) plugin.
- extend_path: Mechanism by which the plugins package path is set.
- plugin_name: Gives unprefixed name of a plugin module.

See the plugin-api developer documentation for information about writing
plugins.
"""

import os
import re
import sys
from importlib import util as importlib_util

import breezy

from . import debug, errors, osutils, trace

_MODULE_PREFIX = "breezy.plugins."

COMPILED_EXT = ".pyc"


def disable_plugins(state=None):
    """Disable loading plugins.

    Future calls to load_plugins() will be ignored.

    Args:
      state: The library state object that records loaded plugins.
    """
    if state is None:
        state = breezy.get_global_state()
    state.plugins = {}


def load_plugins(path=None, state=None, warn_load_problems=True):
    """Load breezy plugins.

    The environment variable BRZ_PLUGIN_PATH is considered a delimited
    set of paths to look through. Each entry is searched for `*.py`
    files (and whatever other extensions are used in the platform,
    such as `*.pyd`).

    Args:
      path: The list of paths to search for plugins.  By default,
        it is populated from the __path__ of the breezy.plugins package.
      state: The library state object that records loaded plugins.
    """
    if state is None:
        state = breezy.get_global_state()
    if getattr(state, "plugins", None) is not None:
        # People can make sure plugins are loaded, they just won't be twice
        return

    if path is None:
        # Calls back into extend_path() here
        from breezy.plugins import __path__ as path

    state.plugin_warnings = {}
    _load_plugins(state, path)
    state.plugins = plugins()
    if warn_load_problems:
        for _plugin, errors in state.plugin_warnings.items():
            for error in errors:
                trace.warning("%s", error)


def plugin_name(module_name):
    """Gives unprefixed name from module_name or None."""
    if module_name.startswith(_MODULE_PREFIX):
        parts = module_name.split(".")
        if len(parts) > 2:
            return parts[2]
    return None


def extend_path(path, name):
    """Helper so breezy.plugins can be a sort of namespace package.

    To be used in similar fashion to pkgutil.extend_path:

        from breezy.plugins import extend_path
        __path__ = extend_path(__path__, __name__)

    Inspects the BRZ_PLUGIN* envvars, sys.path, and the filesystem to find
    plugins. May mutate sys.modules in order to block plugin loading, and may
    append a new meta path finder to sys.meta_path for plugins@ loading.

    Returns a list of paths to import from, as an enhanced object that also
    contains details of the other configuration used.
    """
    blocks = _env_disable_plugins()
    _block_plugins(blocks)

    extra_details = _env_plugins_at()
    _install_importer_if_needed(extra_details)

    paths = _iter_plugin_paths(_env_plugin_path(), path)

    return _Path(name, blocks, extra_details, paths)


class _Path(list):
    """List type to use as __path__ but containing additional details.

    Python 3 allows any iterable for __path__ but Python 2 is more fussy.
    """

    def __init__(self, package_name, blocked, extra, paths):
        super().__init__(paths)
        self.package_name = package_name
        self.blocked_names = blocked
        self.extra_details = extra

    def __repr__(self):
        return "{}({!r}, {!r}, {!r}, {})".format(
            self.__class__.__name__,
            self.package_name,
            self.blocked_names,
            self.extra_details,
            list.__repr__(self),
        )


def _expect_identifier(name, env_key, env_value):
    """Validate given name from envvar is usable as a Python identifier.

    Returns the name as a native str, or None if it was invalid.

    Per PEP 3131 this is no longer strictly correct for Python 3, but as MvL
    didn't include a neat way to check except eval, this enforces ascii.
    """
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) is None:
        trace.warning("Invalid name '%s' in %s='%s'", name, env_key, env_value)
        return None
    return str(name)


def _env_disable_plugins(key="BRZ_DISABLE_PLUGINS"):
    """Gives list of names for plugins to disable from environ key."""
    disabled_names = []
    env = os.environ.get(key)
    if env:
        for name in env.split(os.pathsep):
            name = _expect_identifier(name, key, env)
            if name is not None:
                disabled_names.append(name)
    return disabled_names


def _env_plugins_at(key="BRZ_PLUGINS_AT"):
    """Gives list of names and paths of specific plugins from environ key."""
    plugin_details = []
    env = os.environ.get(key)
    if env:
        for pair in env.split(os.pathsep):
            if "@" in pair:
                name, path = pair.split("@", 1)
            else:
                path = pair
                name = osutils.basename(path).split(".", 1)[0]
            name = _expect_identifier(name, key, env)
            if name is not None:
                plugin_details.append((name, os.path.abspath(path)))
    return plugin_details


def _env_plugin_path(key="BRZ_PLUGIN_PATH"):
    """Gives list of paths and contexts for plugins from environ key.

    Each entry is either a specific path to load plugins from and the value
    'path', or None and one of the three values 'user', 'core', 'site'.
    """
    path_details = []
    env = os.environ.get(key)
    defaults = {
        "user": not env,
        "core": True,
        "site": True,
    }
    if env:
        # Add paths specified by user in order
        for p in env.split(os.pathsep):
            flag, name = p[:1], p[1:]
            if flag in ("+", "-") and name in defaults:
                if flag == "+" and defaults[name] is not None:
                    path_details.append((None, name))
                defaults[name] = None
            else:
                path_details.append((p, "path"))

    # Add any remaining default paths
    for name in ("user", "core", "site"):
        if defaults[name]:
            path_details.append((None, name))

    return path_details


def _iter_plugin_paths(paths_from_env, core_paths):
    """Generate paths using paths_from_env and core_paths."""
    # GZ 2017-06-02: This is kinda horrid, should make better.
    for path, context in paths_from_env:
        if context == "path":
            yield os.path.abspath(path)
        elif context == "user":
            path = get_user_plugin_path()
            if os.path.isdir(path):
                yield path
        elif context == "core":
            for path in _get_core_plugin_paths(core_paths):
                yield path
        elif context == "site":
            for path in _get_site_plugin_paths(sys.path):
                if os.path.isdir(path):
                    yield path


def _install_importer_if_needed(plugin_details):
    """Install a meta path finder to handle plugin_details if any."""
    if plugin_details:
        finder = _PluginsAtFinder(_MODULE_PREFIX, plugin_details)
        # For Python 3, must insert before default PathFinder to override.
        sys.meta_path.insert(2, finder)


def _load_plugins(state, paths):
    """Do the importing all plugins from paths."""
    imported_names = set()
    for name, path in _iter_possible_plugins(paths):
        if name not in imported_names:
            if not valid_plugin_name(name):
                sanitised_name = sanitise_plugin_name(name)
                trace.warning(
                    "Unable to load {!r} in {!r} as a plugin because the "
                    "file path isn't a valid module name; try renaming "
                    "it to {!r}.".format(name, path, sanitised_name)
                )
                continue
            msg = _load_plugin_module(name, path)
            if msg is not None:
                state.plugin_warnings.setdefault(name, []).append(msg)
            imported_names.add(name)


def _block_plugins(names):
    """Add names to sys.modules to block future imports."""
    for name in names:
        package_name = _MODULE_PREFIX + name
        if sys.modules.get(package_name) is not None:
            trace.mutter("Blocked plugin %s already loaded.", name)
        sys.modules[package_name] = None


def _get_package_init(package_path):
    """Get path of __init__ file from package_path or None if not a package."""
    init_path = osutils.pathjoin(package_path, "__init__.py")
    if os.path.exists(init_path):
        return init_path
    init_path = init_path[:-3] + COMPILED_EXT
    if os.path.exists(init_path):
        return init_path
    return None


def _iter_possible_plugins(plugin_paths):
    """Generate names and paths of possible plugins from plugin_paths."""
    # Inspect any from BRZ_PLUGINS_AT first.
    yield from getattr(plugin_paths, "extra_details", ())
    # Then walk over files and directories in the paths from the package.
    for path in plugin_paths:
        if os.path.isfile(path):
            if path.endswith(".zip"):
                trace.mutter("Don't yet support loading plugins from zip.")
        else:
            yield from _walk_modules(path)


def _walk_modules(path):
    """Generate name and path of modules and packages on path."""
    for root, dirs, files in os.walk(path):
        files.sort()
        for f in files:
            if f[:2] != "__":
                if f.endswith((".py", COMPILED_EXT)):
                    yield f.rsplit(".", 1)[0], root
        dirs.sort()
        for d in dirs:
            if d[:2] != "__":
                package_dir = osutils.pathjoin(root, d)
                fullpath = _get_package_init(package_dir)
                if fullpath is not None:
                    yield d, package_dir
        # Don't descend into subdirectories
        del dirs[:]


def describe_plugins(show_paths=False, state=None):
    """Generate text description of plugins.

    Includes both those that have loaded, and those that failed to load.

    Args:
      show_paths: If true, include the plugin path.
      state: The library state object to inspect.

    Returns:
      Iterator of text lines (including newlines.)
    """
    if state is None:
        state = breezy.get_global_state()
    loaded_plugins = getattr(state, "plugins", {})
    plugin_warnings = set(getattr(state, "plugin_warnings", []))
    all_names = sorted(set(loaded_plugins.keys()).union(plugin_warnings))
    for name in all_names:
        if name in loaded_plugins:
            plugin = loaded_plugins[name]
            version = plugin.__version__
            if version == "unknown":
                version = ""
            yield "{} {}\n".format(name, version)
            d = plugin.module.__doc__
            if d:
                doc = d.split("\n")[0]
            else:
                doc = "(no description)"
            yield ("  {}\n".format(doc))
            if show_paths:
                yield ("   {}\n".format(plugin.path()))
        else:
            yield "{} (failed to load)\n".format(name)
        if name in state.plugin_warnings:
            for line in state.plugin_warnings[name]:
                yield "  ** " + line + "\n"
        yield "\n"


def _get_core_plugin_paths(existing_paths):
    """Generate possible locations for plugins based on existing_paths."""
    if getattr(sys, "frozen", False):
        # We need to use relative path to system-wide plugin
        # directory because breezy from standalone brz.exe
        # could be imported by another standalone program
        # (e.g. brz-config; or TortoiseBzr/Olive if/when they
        # will become standalone exe). [bialix 20071123]
        # __file__ typically is
        # C:\Program Files\Bazaar\lib\library.zip\breezy\plugin.pyc
        # then plugins directory is
        # C:\Program Files\Bazaar\plugins
        # so relative path is ../../../plugins
        yield osutils.abspath(
            osutils.pathjoin(osutils.dirname(__file__), "../../../plugins")
        )
    else:  # don't look inside library.zip
        for path in existing_paths:
            yield osutils.abspath(path)


def _get_site_plugin_paths(sys_paths):
    """Generate possible locations for plugins from given sys_paths."""
    for path in sys_paths:
        if os.path.basename(path) in ("dist-packages", "site-packages"):
            yield osutils.pathjoin(path, "breezy", "plugins")


def get_user_plugin_path():
    from breezy.bedding import config_dir

    return osutils.pathjoin(config_dir(), "plugins")


def record_plugin_warning(warning_message):
    trace.mutter(warning_message)
    return warning_message


def valid_plugin_name(name):
    return not re.search("\\.|-| ", name)


def sanitise_plugin_name(name):
    sanitised_name = re.sub("[-. ]", "_", name)
    if sanitised_name.startswith("brz_"):
        sanitised_name = sanitised_name[len("brz_") :]
    return sanitised_name


def _load_plugin_module(name, dir):
    """Load plugin by name.

    Args:
      name: The plugin name in the breezy.plugins namespace.
      dir: The directory the plugin is loaded from for error messages.
    """
    if _MODULE_PREFIX + name in sys.modules:
        return
    try:
        __import__(_MODULE_PREFIX + name)
    except errors.IncompatibleVersion as e:
        warning_message = (
            "Unable to load plugin {!r}. It supports {} "
            "versions {!r} but the current version is {}".format(name, e.api.__name__, e.wanted, e.current)
        )
        return record_plugin_warning(warning_message)
    except Exception as e:
        trace.log_exception_quietly()
        if "error" in debug.debug_flags:
            trace.print_exception(sys.exc_info(), sys.stderr)
        return record_plugin_warning(
            "Unable to load plugin {!r} from {!r}: {}".format(name, dir, e)
        )


def plugins():
    """Return a dictionary of the plugins.

    Each item in the dictionary is a PlugIn object.
    """
    result = {}
    for fullname in sys.modules:
        if fullname.startswith(_MODULE_PREFIX):
            name = fullname[len(_MODULE_PREFIX) :]
            if "." not in name and sys.modules[fullname] is not None:
                result[name] = PlugIn(name, sys.modules[fullname])
    return result


def get_loaded_plugin(name):
    """Retrieve an already loaded plugin.

    Returns None if there is no such plugin loaded
    """
    try:
        module = sys.modules[_MODULE_PREFIX + name]
    except KeyError:
        return None
    if module is None:
        return None
    return PlugIn(name, module)


def format_concise_plugin_list(state=None):
    """Return a string holding a concise list of plugins and their version."""
    if state is None:
        state = breezy.get_global_state()
    items = []
    for name, a_plugin in sorted(getattr(state, "plugins", {}).items()):
        items.append("{}[{}]".format(name, a_plugin.__version__))
    return ", ".join(items)


class PluginsHelpIndex:
    """A help index that returns help topics for plugins."""

    def __init__(self):
        self.prefix = "plugins/"

    def get_topics(self, topic):
        """Search for topic in the loaded plugins.

        This will not trigger loading of new plugins.

        Args:
          topic: A topic to search for.

        Returns:
          A list which is either empty or contains a single
          RegisteredTopic entry.
        """
        if not topic:
            return []
        if topic.startswith(self.prefix):
            topic = topic[len(self.prefix) :]
        plugin_module_name = _MODULE_PREFIX + topic
        try:
            module = sys.modules[plugin_module_name]
        except KeyError:
            return []
        else:
            return [ModuleHelpTopic(module)]


class ModuleHelpTopic:
    """A help topic which returns the docstring for a module."""

    def __init__(self, module):
        """Constructor.

        Args:
          module: The module for which help should be generated.
        """
        self.module = module

    def get_help_text(self, additional_see_also=None, verbose=True):
        """Return a string with the help for this topic.

        Args:
          additional_see_also: Additional help topics to be
            cross-referenced.
        """
        from . import help_topics

        if not self.module.__doc__:
            result = "Plugin '{}' has no docstring.\n".format(self.module.__name__)
        else:
            result = self.module.__doc__
        if result[-1] != "\n":
            result += "\n"
        result += help_topics._format_see_also(additional_see_also)
        return result

    def get_help_topic(self):
        """Return the module help topic: its basename."""
        return self.module.__name__[len(_MODULE_PREFIX) :]


class PlugIn:
    """The breezy representation of a plugin.

    The PlugIn object provides a way to manipulate a given plugin module.
    """

    def __init__(self, name, module):
        """Construct a plugin for module."""
        self.name = name
        self.module = module

    def path(self):
        """Get the path that this plugin was loaded from."""
        if getattr(self.module, "__path__", None) is not None:
            return os.path.abspath(self.module.__path__[0])
        elif getattr(self.module, "__file__", None) is not None:
            path = os.path.abspath(self.module.__file__)
            if path[-4:] == COMPILED_EXT:
                pypath = path[:-4] + ".py"
                if os.path.isfile(pypath):
                    path = pypath
            return path
        else:
            return repr(self.module)

    def __repr__(self):
        return "<{}.{} name={}, module={}>".format(
            self.__class__.__module__, self.__class__.__name__, self.name, self.module
        )

    def test_suite(self):
        """Return the plugin's test suite."""
        if getattr(self.module, "test_suite", None) is not None:
            return self.module.test_suite()
        else:
            return None

    def load_plugin_tests(self, loader):
        """Return the adapted plugin's test suite.

        Args:
          loader: The custom loader that should be used to load additional
            tests.
        """
        if getattr(self.module, "load_tests", None) is not None:
            return loader.loadTestsFromModule(self.module)
        else:
            return None

    def version_info(self):
        """Return the plugin's version_tuple or None if unknown."""
        version_info = getattr(self.module, "version_info", None)
        if version_info is not None:
            try:
                if isinstance(version_info, str):
                    version_info = version_info.split(".")
                elif len(version_info) == 3:
                    version_info = tuple(version_info) + ("final", 0)
            except TypeError:
                # The given version_info isn't even iteratible
                trace.log_exception_quietly()
                version_info = (version_info,)
        return version_info

    @property
    def __version__(self):
        version_info = self.version_info()
        if version_info is None or len(version_info) == 0:
            return "unknown"
        try:
            version_string = breezy._format_version_tuple(version_info)
        except (ValueError, TypeError, IndexError):
            trace.log_exception_quietly()
            # Try to show something for the version anyway
            version_string = ".".join(map(str, version_info))
        return version_string


class _PluginsAtFinder:
    """Meta path finder to support BRZ_PLUGINS_AT configuration."""

    def __init__(self, prefix, names_and_paths):
        self.prefix = prefix
        self.names_to_path = {prefix + n: p for n, p in names_and_paths}

    def __repr__(self):
        return "<{} {!r}>".format(self.__class__.__name__, self.prefix)

    def find_spec(self, fullname, paths, target=None):
        """New module spec returning find method."""
        if fullname not in self.names_to_path:
            return None
        path = self.names_to_path[fullname]
        if os.path.isdir(path):
            path = _get_package_init(path)
            if path is None:
                # GZ 2017-06-02: Any reason to block loading of the name from
                # further down the path like this?
                raise ImportError(
                    "Not loading namespace package {} as {}".format(path, fullname)
                )
        return importlib_util.spec_from_file_location(fullname, path)
