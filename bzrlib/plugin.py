# Copyright (C) 2005-2011 Canonical Ltd
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

"""bzr python plugin support.

When load_plugins() is invoked, any python module in any directory in
$BZR_PLUGIN_PATH will be imported.  The module will be imported as
'bzrlib.plugins.$BASENAME(PLUGIN)'.  In the plugin's main body, it should
update any bzrlib registries it wants to extend.

See the plugin-api developer documentation for information about writing
plugins.

BZR_PLUGIN_PATH is also honoured for any plugins imported via
'import bzrlib.plugins.PLUGINNAME', as long as set_plugins_path has been
called.
"""

from __future__ import absolute_import

import os
import sys

from bzrlib import osutils

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import imp
import re
import types

from bzrlib import (
    _format_version_tuple,
    config,
    debug,
    errors,
    trace,
    )
from bzrlib.i18n import gettext
from bzrlib import plugins as _mod_plugins
""")


DEFAULT_PLUGIN_PATH = None
_loaded = False
_plugins_disabled = False


plugin_warnings = {}
# Map from plugin name, to list of string warnings about eg plugin
# dependencies.


def are_plugins_disabled():
    return _plugins_disabled


def disable_plugins():
    """Disable loading plugins.

    Future calls to load_plugins() will be ignored.
    """
    global _plugins_disabled
    _plugins_disabled = True
    load_plugins([])


def describe_plugins(show_paths=False):
    """Generate text description of plugins.

    Includes both those that have loaded, and those that failed to 
    load.

    :param show_paths: If true,
    :returns: Iterator of text lines (including newlines.)
    """
    from inspect import getdoc
    loaded_plugins = plugins()
    all_names = sorted(list(set(
        loaded_plugins.keys() + plugin_warnings.keys())))
    for name in all_names:
        if name in loaded_plugins:
            plugin = loaded_plugins[name]
            version = plugin.__version__
            if version == 'unknown':
                version = ''
            yield '%s %s\n' % (name, version)
            d = getdoc(plugin.module)
            if d:
                doc = d.split('\n')[0]
            else:
                doc = '(no description)'
            yield ("  %s\n" % doc)
            if show_paths:
                yield ("   %s\n" % plugin.path())
            del plugin
        else:
            yield "%s (failed to load)\n" % name
        if name in plugin_warnings:
            for line in plugin_warnings[name]:
                yield "  ** " + line + '\n'
        yield '\n'


def _strip_trailing_sep(path):
    return path.rstrip("\\/")


def _get_specific_plugin_paths(paths):
    """Returns the plugin paths from a string describing the associations.

    :param paths: A string describing the paths associated with the plugins.

    :returns: A list of (plugin name, path) tuples.

    For example, if paths is my_plugin@/test/my-test:her_plugin@/production/her,
    [('my_plugin', '/test/my-test'), ('her_plugin', '/production/her')] 
    will be returned.

    Note that ':' in the example above depends on the os.
    """
    if not paths:
        return []
    specs = []
    for spec in paths.split(os.pathsep):
        try:
            name, path = spec.split('@')
        except ValueError:
            raise errors.BzrCommandError(gettext(
                '"%s" is not a valid <plugin_name>@<plugin_path> description ')
                % spec)
        specs.append((name, path))
    return specs


def set_plugins_path(path=None):
    """Set the path for plugins to be loaded from.

    :param path: The list of paths to search for plugins.  By default,
        path will be determined using get_standard_plugins_path.
        if path is [], no plugins can be loaded.
    """
    if path is None:
        path = get_standard_plugins_path()
    _mod_plugins.__path__ = path
    PluginImporter.reset()
    # Set up a blacklist for disabled plugins
    disabled_plugins = os.environ.get('BZR_DISABLE_PLUGINS', None)
    if disabled_plugins is not None:
        for name in disabled_plugins.split(os.pathsep):
            PluginImporter.blacklist.add('bzrlib.plugins.' + name)
    # Set up a the specific paths for plugins
    for plugin_name, plugin_path in _get_specific_plugin_paths(os.environ.get(
            'BZR_PLUGINS_AT', None)):
            PluginImporter.specific_paths[
                'bzrlib.plugins.%s' % plugin_name] = plugin_path
    return path


def _append_new_path(paths, new_path):
    """Append a new path if it set and not already known."""
    if new_path is not None and new_path not in paths:
        paths.append(new_path)
    return paths


def get_core_plugin_path():
    core_path = None
    bzr_exe = bool(getattr(sys, 'frozen', None))
    if bzr_exe:    # expand path for bzr.exe
        # We need to use relative path to system-wide plugin
        # directory because bzrlib from standalone bzr.exe
        # could be imported by another standalone program
        # (e.g. bzr-config; or TortoiseBzr/Olive if/when they
        # will become standalone exe). [bialix 20071123]
        # __file__ typically is
        # C:\Program Files\Bazaar\lib\library.zip\bzrlib\plugin.pyc
        # then plugins directory is
        # C:\Program Files\Bazaar\plugins
        # so relative path is ../../../plugins
        core_path = osutils.abspath(osutils.pathjoin(
                osutils.dirname(__file__), '../../../plugins'))
    else:     # don't look inside library.zip
        # search the plugin path before the bzrlib installed dir
        core_path = os.path.dirname(_mod_plugins.__file__)
    return core_path


def get_site_plugin_path():
    """Returns the path for the site installed plugins."""
    if sys.platform == 'win32':
        # We don't have (yet) a good answer for windows since that is certainly
        # related to the way we build the installers. -- vila20090821
        return None
    site_path = None
    try:
        from distutils.sysconfig import get_python_lib
    except ImportError:
        # If distutuils is not available, we just don't know where they are
        pass
    else:
        site_path = osutils.pathjoin(get_python_lib(), 'bzrlib', 'plugins')
    return site_path


def get_user_plugin_path():
    return osutils.pathjoin(config.config_dir(), 'plugins')


def get_standard_plugins_path():
    """Determine a plugin path suitable for general use."""
    # Ad-Hoc default: core is not overriden by site but user can overrides both
    # The rationale is that:
    # - 'site' comes last, because these plugins should always be available and
    #   are supposed to be in sync with the bzr installed on site.
    # - 'core' comes before 'site' so that running bzr from sources or a user
    #   installed version overrides the site version.
    # - 'user' comes first, because... user is always right.
    # - the above rules clearly defines which plugin version will be loaded if
    #   several exist. Yet, it is sometimes desirable to disable some directory
    #   so that a set of plugins is disabled as once. This can be done via
    #   -site, -core, -user.

    env_paths = os.environ.get('BZR_PLUGIN_PATH', '+user').split(os.pathsep)
    defaults = ['+core', '+site']

    # The predefined references
    refs = dict(core=get_core_plugin_path(),
                site=get_site_plugin_path(),
                user=get_user_plugin_path())

    # Unset paths that should be removed
    for k,v in refs.iteritems():
        removed = '-%s' % k
        # defaults can never mention removing paths as that will make it
        # impossible for the user to revoke these removals.
        if removed in env_paths:
            env_paths.remove(removed)
            refs[k] = None

    # Expand references
    paths = []
    for p in env_paths + defaults:
        if p.startswith('+'):
            # Resolve references if they are known
            try:
                p = refs[p[1:]]
            except KeyError:
                # Leave them untouched so user can still use paths starting
                # with '+'
                pass
        _append_new_path(paths, p)

    # Get rid of trailing slashes, since Python can't handle them when
    # it tries to import modules.
    paths = map(_strip_trailing_sep, paths)
    return paths


def load_plugins(path=None):
    """Load bzrlib plugins.

    The environment variable BZR_PLUGIN_PATH is considered a delimited
    set of paths to look through. Each entry is searched for `*.py`
    files (and whatever other extensions are used in the platform,
    such as `*.pyd`).

    load_from_path() provides the underlying mechanism and is called with
    the default directory list to provide the normal behaviour.

    :param path: The list of paths to search for plugins.  By default,
        path will be determined using get_standard_plugins_path.
        if path is [], no plugins can be loaded.
    """
    global _loaded
    if _loaded:
        # People can make sure plugins are loaded, they just won't be twice
        return
    _loaded = True

    # scan for all plugins in the path.
    load_from_path(set_plugins_path(path))


def load_from_path(dirs):
    """Load bzrlib plugins found in each dir in dirs.

    Loading a plugin means importing it into the python interpreter.
    The plugin is expected to make calls to register commands when
    it's loaded (or perhaps access other hooks in future.)

    Plugins are loaded into bzrlib.plugins.NAME, and can be found there
    for future reference.

    The python module path for bzrlib.plugins will be modified to be 'dirs'.
    """
    # Explicitly load the plugins with a specific path
    for fullname, path in PluginImporter.specific_paths.iteritems():
        name = fullname[len('bzrlib.plugins.'):]
        _load_plugin_module(name, path)

    # We need to strip the trailing separators here as well as in the
    # set_plugins_path function because calling code can pass anything in to
    # this function, and since it sets plugins.__path__, it should set it to
    # something that will be valid for Python to use (in case people try to
    # run "import bzrlib.plugins.PLUGINNAME" after calling this function).
    _mod_plugins.__path__ = map(_strip_trailing_sep, dirs)
    for d in dirs:
        if not d:
            continue
        trace.mutter('looking for plugins in %s', d)
        if os.path.isdir(d):
            load_from_dir(d)


# backwards compatability: load_from_dirs was the old name
# This was changed in 0.15
load_from_dirs = load_from_path


def _find_plugin_module(dir, name):
    """Check if there is a valid python module that can be loaded as a plugin.

    :param dir: The directory where the search is performed.
    :param path: An existing file path, either a python file or a package
        directory.

    :return: (name, path, description) name is the module name, path is the
        file to load and description is the tuple returned by
        imp.get_suffixes().
    """
    path = osutils.pathjoin(dir, name)
    if os.path.isdir(path):
        # Check for a valid __init__.py file, valid suffixes depends on -O and
        # can be .py, .pyc and .pyo
        for suffix, mode, kind in imp.get_suffixes():
            if kind not in (imp.PY_SOURCE, imp.PY_COMPILED):
                # We don't recognize compiled modules (.so, .dll, etc)
                continue
            init_path = osutils.pathjoin(path, '__init__' + suffix)
            if os.path.isfile(init_path):
                return name, init_path, (suffix, mode, kind)
    else:
        for suffix, mode, kind in imp.get_suffixes():
            if name.endswith(suffix):
                # Clean up the module name
                name = name[:-len(suffix)]
                if kind == imp.C_EXTENSION and name.endswith('module'):
                    name = name[:-len('module')]
                return name, path, (suffix, mode, kind)
    # There is no python module here
    return None, None, (None, None, None)


def record_plugin_warning(plugin_name, warning_message):
    trace.mutter(warning_message)
    plugin_warnings.setdefault(plugin_name, []).append(warning_message)


def _load_plugin_module(name, dir):
    """Load plugin name from dir.

    :param name: The plugin name in the bzrlib.plugins namespace.
    :param dir: The directory the plugin is loaded from for error messages.
    """
    if ('bzrlib.plugins.%s' % name) in PluginImporter.blacklist:
        return
    try:
        exec "import bzrlib.plugins.%s" % name in {}
    except KeyboardInterrupt:
        raise
    except errors.IncompatibleAPI, e:
        warning_message = (
            "Unable to load plugin %r. It requested API version "
            "%s of module %s but the minimum exported version is %s, and "
            "the maximum is %s" %
            (name, e.wanted, e.api, e.minimum, e.current))
        record_plugin_warning(name, warning_message)
    except Exception, e:
        trace.warning("%s" % e)
        if re.search('\.|-| ', name):
            sanitised_name = re.sub('[-. ]', '_', name)
            if sanitised_name.startswith('bzr_'):
                sanitised_name = sanitised_name[len('bzr_'):]
            trace.warning("Unable to load %r in %r as a plugin because the "
                    "file path isn't a valid module name; try renaming "
                    "it to %r." % (name, dir, sanitised_name))
        else:
            record_plugin_warning(
                name,
                'Unable to load plugin %r from %r' % (name, dir))
        trace.log_exception_quietly()
        if 'error' in debug.debug_flags:
            trace.print_exception(sys.exc_info(), sys.stderr)


def load_from_dir(d):
    """Load the plugins in directory d.

    d must be in the plugins module path already.
    This function is called once for each directory in the module path.
    """
    plugin_names = set()
    for p in os.listdir(d):
        name, path, desc = _find_plugin_module(d, p)
        if name is not None:
            if name == '__init__':
                # We do nothing with the __init__.py file in directories from
                # the bzrlib.plugins module path, we may want to, one day
                # -- vila 20100316.
                continue # We don't load __init__.py in the plugins dirs
            elif getattr(_mod_plugins, name, None) is not None:
                # The module has already been loaded from another directory
                # during a previous call.
                # FIXME: There should be a better way to report masked plugins
                # -- vila 20100316
                trace.mutter('Plugin name %s already loaded', name)
            else:
                plugin_names.add(name)

    for name in plugin_names:
        _load_plugin_module(name, d)


def plugins():
    """Return a dictionary of the plugins.

    Each item in the dictionary is a PlugIn object.
    """
    result = {}
    for name, plugin in _mod_plugins.__dict__.items():
        if isinstance(plugin, types.ModuleType):
            result[name] = PlugIn(name, plugin)
    return result


def format_concise_plugin_list():
    """Return a string holding a concise list of plugins and their version.
    """
    items = []
    for name, a_plugin in sorted(plugins().items()):
        items.append("%s[%s]" %
            (name, a_plugin.__version__))
    return ', '.join(items)



class PluginsHelpIndex(object):
    """A help index that returns help topics for plugins."""

    def __init__(self):
        self.prefix = 'plugins/'

    def get_topics(self, topic):
        """Search for topic in the loaded plugins.

        This will not trigger loading of new plugins.

        :param topic: A topic to search for.
        :return: A list which is either empty or contains a single
            RegisteredTopic entry.
        """
        if not topic:
            return []
        if topic.startswith(self.prefix):
            topic = topic[len(self.prefix):]
        plugin_module_name = 'bzrlib.plugins.%s' % topic
        try:
            module = sys.modules[plugin_module_name]
        except KeyError:
            return []
        else:
            return [ModuleHelpTopic(module)]


class ModuleHelpTopic(object):
    """A help topic which returns the docstring for a module."""

    def __init__(self, module):
        """Constructor.

        :param module: The module for which help should be generated.
        """
        self.module = module

    def get_help_text(self, additional_see_also=None, verbose=True):
        """Return a string with the help for this topic.

        :param additional_see_also: Additional help topics to be
            cross-referenced.
        """
        if not self.module.__doc__:
            result = "Plugin '%s' has no docstring.\n" % self.module.__name__
        else:
            result = self.module.__doc__
        if result[-1] != '\n':
            result += '\n'
        from bzrlib import help_topics
        result += help_topics._format_see_also(additional_see_also)
        return result

    def get_help_topic(self):
        """Return the module help topic: its basename."""
        return self.module.__name__[len('bzrlib.plugins.'):]


class PlugIn(object):
    """The bzrlib representation of a plugin.

    The PlugIn object provides a way to manipulate a given plugin module.
    """

    def __init__(self, name, module):
        """Construct a plugin for module."""
        self.name = name
        self.module = module

    def path(self):
        """Get the path that this plugin was loaded from."""
        if getattr(self.module, '__path__', None) is not None:
            return os.path.abspath(self.module.__path__[0])
        elif getattr(self.module, '__file__', None) is not None:
            path = os.path.abspath(self.module.__file__)
            if path[-4:] in ('.pyc', '.pyo'):
                pypath = path[:-4] + '.py'
                if os.path.isfile(pypath):
                    path = pypath
            return path
        else:
            return repr(self.module)

    def __str__(self):
        return "<%s.%s object at %s, name=%s, module=%s>" % (
            self.__class__.__module__, self.__class__.__name__, id(self),
            self.name, self.module)

    __repr__ = __str__

    def test_suite(self):
        """Return the plugin's test suite."""
        if getattr(self.module, 'test_suite', None) is not None:
            return self.module.test_suite()
        else:
            return None

    def load_plugin_tests(self, loader):
        """Return the adapted plugin's test suite.

        :param loader: The custom loader that should be used to load additional
            tests.

        """
        if getattr(self.module, 'load_tests', None) is not None:
            return loader.loadTestsFromModule(self.module)
        else:
            return None

    def version_info(self):
        """Return the plugin's version_tuple or None if unknown."""
        version_info = getattr(self.module, 'version_info', None)
        if version_info is not None:
            try:
                if isinstance(version_info, types.StringType):
                    version_info = version_info.split('.')
                elif len(version_info) == 3:
                    version_info = tuple(version_info) + ('final', 0)
            except TypeError, e:
                # The given version_info isn't even iteratible
                trace.log_exception_quietly()
                version_info = (version_info,)
        return version_info

    def _get__version__(self):
        version_info = self.version_info()
        if version_info is None or len(version_info) == 0:
            return "unknown"
        try:
            version_string = _format_version_tuple(version_info)
        except (ValueError, TypeError, IndexError), e:
            trace.log_exception_quietly()
            # try to return something usefull for bad plugins, in stead of
            # stack tracing.
            version_string = '.'.join(map(str, version_info))
        return version_string

    __version__ = property(_get__version__)


class _PluginImporter(object):
    """An importer tailored to bzr specific needs.

    This is a singleton that takes care of:
    - disabled plugins specified in 'blacklist',
    - plugins that needs to be loaded from specific directories.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.blacklist = set()
        self.specific_paths = {}

    def find_module(self, fullname, parent_path=None):
        """Search a plugin module.

        Disabled plugins raise an import error, plugins with specific paths
        returns a specific loader.

        :return: None if the plugin doesn't need special handling, self
            otherwise.
        """
        if not fullname.startswith('bzrlib.plugins.'):
            return None
        if fullname in self.blacklist:
            raise ImportError('%s is disabled' % fullname)
        if fullname in self.specific_paths:
            return self
        return None

    def load_module(self, fullname):
        """Load a plugin from a specific directory (or file)."""
        # We are called only for specific paths
        plugin_path = self.specific_paths[fullname]
        loading_path = None
        if os.path.isdir(plugin_path):
            for suffix, mode, kind in imp.get_suffixes():
                if kind not in (imp.PY_SOURCE, imp.PY_COMPILED):
                    # We don't recognize compiled modules (.so, .dll, etc)
                    continue
                init_path = osutils.pathjoin(plugin_path, '__init__' + suffix)
                if os.path.isfile(init_path):
                    # We've got a module here and load_module needs specific
                    # parameters.
                    loading_path = plugin_path
                    suffix = ''
                    mode = ''
                    kind = imp.PKG_DIRECTORY
                    break
        else:
            for suffix, mode, kind in imp.get_suffixes():
                if plugin_path.endswith(suffix):
                    loading_path = plugin_path
                    break
        if loading_path is None:
            raise ImportError('%s cannot be loaded from %s'
                              % (fullname, plugin_path))
        if kind is imp.PKG_DIRECTORY:
            f = None
        else:
            f = open(loading_path, mode)
        try:
            mod = imp.load_module(fullname, f, loading_path,
                                  (suffix, mode, kind))
            mod.__package__ = fullname
            return mod
        finally:
            if f is not None:
                f.close()


# Install a dedicated importer for plugins requiring special handling
PluginImporter = _PluginImporter()
sys.meta_path.append(PluginImporter)
