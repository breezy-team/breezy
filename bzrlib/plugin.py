# Copyright (C) 2004, 2005, 2007 Canonical Ltd
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


"""bzr python plugin support.

When load_plugins() is invoked, any python module in any directory in
$BZR_PLUGIN_PATH will be imported.  The module will be imported as
'bzrlib.plugins.$BASENAME(PLUGIN)'.  In the plugin's main body, it should
update any bzrlib registries it wants to extend; for example, to add new
commands, import bzrlib.commands and add your new command to the plugin_cmds
variable.

BZR_PLUGIN_PATH is also honoured for any plugins imported via
'import bzrlib.plugins.PLUGINNAME', as long as set_plugins_path has been 
called.
"""

import os
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import imp
import re
import types
import zipfile

from bzrlib import (
    config,
    debug,
    osutils,
    trace,
    )
from bzrlib import plugins as _mod_plugins
""")

from bzrlib.symbol_versioning import deprecated_function, one_three
from bzrlib.trace import mutter, warning, log_exception_quietly


DEFAULT_PLUGIN_PATH = None
_loaded = False

def get_default_plugin_path():
    """Get the DEFAULT_PLUGIN_PATH"""
    global DEFAULT_PLUGIN_PATH
    if DEFAULT_PLUGIN_PATH is None:
        DEFAULT_PLUGIN_PATH = osutils.pathjoin(config.config_dir(), 'plugins')
    return DEFAULT_PLUGIN_PATH


def disable_plugins():
    """Disable loading plugins.

    Future calls to load_plugins() will be ignored.
    """
    # TODO: jam 20060131 This should probably also disable
    #       load_from_dirs()
    global _loaded
    _loaded = True


def _strip_trailing_sep(path):
    return path.rstrip("\\/")


def set_plugins_path():
    """Set the path for plugins to be loaded from."""
    path = os.environ.get('BZR_PLUGIN_PATH',
                          get_default_plugin_path()).split(os.pathsep)
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
        path.append(osutils.abspath(osutils.pathjoin(
            osutils.dirname(__file__), '../../../plugins')))
    # Get rid of trailing slashes, since Python can't handle them when
    # it tries to import modules.
    path = map(_strip_trailing_sep, path)
    if not bzr_exe:     # don't look inside library.zip
        # search the plugin path before the bzrlib installed dir
        path.append(os.path.dirname(_mod_plugins.__file__))
    # search the arch independent path if we can determine that and
    # the plugin is found nowhere else
    if sys.platform != 'win32':
        try:
            from distutils.sysconfig import get_python_lib
        except ImportError:
            # If distutuils is not available, we just won't add that path
            pass
        else:
            archless_path = osutils.pathjoin(get_python_lib(), 'bzrlib',
                    'plugins')
            if archless_path not in path:
                path.append(archless_path)
    _mod_plugins.__path__ = path
    return path


def load_plugins():
    """Load bzrlib plugins.

    The environment variable BZR_PLUGIN_PATH is considered a delimited
    set of paths to look through. Each entry is searched for *.py
    files (and whatever other extensions are used in the platform,
    such as *.pyd).

    load_from_dirs() provides the underlying mechanism and is called with
    the default directory list to provide the normal behaviour.
    """
    global _loaded
    if _loaded:
        # People can make sure plugins are loaded, they just won't be twice
        return
    _loaded = True

    # scan for all plugins in the path.
    load_from_path(set_plugins_path())


def load_from_path(dirs):
    """Load bzrlib plugins found in each dir in dirs.

    Loading a plugin means importing it into the python interpreter.
    The plugin is expected to make calls to register commands when
    it's loaded (or perhaps access other hooks in future.)

    Plugins are loaded into bzrlib.plugins.NAME, and can be found there
    for future reference.

    The python module path for bzrlib.plugins will be modified to be 'dirs'.
    """
    # We need to strip the trailing separators here as well as in the
    # set_plugins_path function because calling code can pass anything in to
    # this function, and since it sets plugins.__path__, it should set it to
    # something that will be valid for Python to use (in case people try to
    # run "import bzrlib.plugins.PLUGINNAME" after calling this function).
    _mod_plugins.__path__ = map(_strip_trailing_sep, dirs)
    for d in dirs:
        if not d:
            continue
        mutter('looking for plugins in %s', d)
        if os.path.isdir(d):
            load_from_dir(d)


# backwards compatability: load_from_dirs was the old name
# This was changed in 0.15
load_from_dirs = load_from_path


def load_from_dir(d):
    """Load the plugins in directory d."""
    # Get the list of valid python suffixes for __init__.py?
    # this includes .py, .pyc, and .pyo (depending on if we are running -O)
    # but it doesn't include compiled modules (.so, .dll, etc)
    valid_suffixes = [suffix for suffix, mod_type, flags in imp.get_suffixes()
                              if flags in (imp.PY_SOURCE, imp.PY_COMPILED)]
    package_entries = ['__init__'+suffix for suffix in valid_suffixes]
    plugin_names = set()
    for f in os.listdir(d):
        path = osutils.pathjoin(d, f)
        if os.path.isdir(path):
            for entry in package_entries:
                # This directory should be a package, and thus added to
                # the list
                if os.path.isfile(osutils.pathjoin(path, entry)):
                    break
            else: # This directory is not a package
                continue
        else:
            for suffix_info in imp.get_suffixes():
                if f.endswith(suffix_info[0]):
                    f = f[:-len(suffix_info[0])]
                    if suffix_info[2] == imp.C_EXTENSION and f.endswith('module'):
                        f = f[:-len('module')]
                    break
            else:
                continue
        if getattr(_mod_plugins, f, None):
            mutter('Plugin name %s already loaded', f)
        else:
            # mutter('add plugin name %s', f)
            plugin_names.add(f)
    
    for name in plugin_names:
        try:
            exec "import bzrlib.plugins.%s" % name in {}
        except KeyboardInterrupt:
            raise
        except Exception, e:
            ## import pdb; pdb.set_trace()
            if re.search('\.|-| ', name):
                sanitised_name = re.sub('[-. ]', '_', name)
                if sanitised_name.startswith('bzr_'):
                    sanitised_name = sanitised_name[len('bzr_'):]
                warning("Unable to load %r in %r as a plugin because the "
                        "file path isn't a valid module name; try renaming "
                        "it to %r." % (name, d, sanitised_name))
            else:
                warning('Unable to load plugin %r from %r' % (name, d))
            log_exception_quietly()
            if 'error' in debug.debug_flags:
                trace.print_exception(sys.exc_info(), sys.stderr)


@deprecated_function(one_three)
def load_from_zip(zip_name):
    """Load all the plugins in a zip."""
    valid_suffixes = ('.py', '.pyc', '.pyo')    # only python modules/packages
                                                # is allowed
    try:
        index = zip_name.rindex('.zip')
    except ValueError:
        return
    archive = zip_name[:index+4]
    prefix = zip_name[index+5:]

    mutter('Looking for plugins in %r', zip_name)

    # use zipfile to get list of files/dirs inside zip
    try:
        z = zipfile.ZipFile(archive)
        namelist = z.namelist()
        z.close()
    except zipfile.error:
        # not a valid zip
        return

    if prefix:
        prefix = prefix.replace('\\','/')
        if prefix[-1] != '/':
            prefix += '/'
        ix = len(prefix)
        namelist = [name[ix:]
                    for name in namelist
                    if name.startswith(prefix)]

    mutter('Names in archive: %r', namelist)
    
    for name in namelist:
        if not name or name.endswith('/'):
            continue
    
        # '/' is used to separate pathname components inside zip archives
        ix = name.rfind('/')
        if ix == -1:
            head, tail = '', name
        else:
            head, tail = name.rsplit('/',1)
        if '/' in head:
            # we don't need looking in subdirectories
            continue
    
        base, suffix = osutils.splitext(tail)
        if suffix not in valid_suffixes:
            continue
    
        if base == '__init__':
            # package
            plugin_name = head
        elif head == '':
            # module
            plugin_name = base
        else:
            continue
    
        if not plugin_name:
            continue
        if getattr(_mod_plugins, plugin_name, None):
            mutter('Plugin name %s already loaded', plugin_name)
            continue
    
        try:
            exec "import bzrlib.plugins.%s" % plugin_name in {}
            mutter('Load plugin %s from zip %r', plugin_name, zip_name)
        except KeyboardInterrupt:
            raise
        except Exception, e:
            ## import pdb; pdb.set_trace()
            warning('Unable to load plugin %r from %r'
                    % (name, zip_name))
            log_exception_quietly()
            if 'error' in debug.debug_flags:
                trace.print_exception(sys.exc_info(), sys.stderr)


def plugins():
    """Return a dictionary of the plugins.
    
    Each item in the dictionary is a PlugIn object.
    """
    result = {}
    for name, plugin in _mod_plugins.__dict__.items():
        if isinstance(plugin, types.ModuleType):
            result[name] = PlugIn(name, plugin)
    return result


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

    def get_help_text(self, additional_see_also=None):
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
        # there is code duplicated here and in bzrlib/help_topic.py's 
        # matching Topic code. This should probably be factored in
        # to a helper function and a common base class.
        if additional_see_also is not None:
            see_also = sorted(set(additional_see_also))
        else:
            see_also = None
        if see_also:
            result += 'See also: '
            result += ', '.join(see_also)
            result += '\n'
        return result

    def get_help_topic(self):
        """Return the modules help topic - its __name__ after bzrlib.plugins.."""
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
        if version_info is not None and len(version_info) == 3:
            version_info = tuple(version_info) + ('final', 0)
        return version_info

    def _get__version__(self):
        version_info = self.version_info()
        if version_info is None:
            return "unknown"
        if version_info[3] == 'final':
            version_string = '%d.%d.%d' % version_info[:3]
        else:
            version_string = '%d.%d.%d%s%d' % version_info
        return version_string

    __version__ = property(_get__version__)
