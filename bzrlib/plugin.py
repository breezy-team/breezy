# Copyright (C) 2004, 2005 Canonical Ltd
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
import zipimport

from bzrlib import (
    config,
    osutils,
    plugins,
    )
""")

from bzrlib.trace import mutter, warning, log_exception_quietly


DEFAULT_PLUGIN_PATH = None
_loaded = False

def get_default_plugin_path():
    """Get the DEFAULT_PLUGIN_PATH"""
    global DEFAULT_PLUGIN_PATH
    if DEFAULT_PLUGIN_PATH is None:
        DEFAULT_PLUGIN_PATH = osutils.pathjoin(config.config_dir(), 'plugins')
    return DEFAULT_PLUGIN_PATH


def all_plugins():
    """Return a dictionary of the plugins."""
    result = {}
    for name, plugin in plugins.__dict__.items():
        if isinstance(plugin, types.ModuleType):
            result[name] = plugin
    return result


def disable_plugins():
    """Disable loading plugins.

    Future calls to load_plugins() will be ignored.
    """
    # TODO: jam 20060131 This should probably also disable
    #       load_from_dirs()
    global _loaded
    _loaded = True


def set_plugins_path():
    """Set the path for plugins to be loaded from."""
    path = os.environ.get('BZR_PLUGIN_PATH',
                          get_default_plugin_path()).split(os.pathsep)
    # search the plugin path before the bzrlib installed dir
    path.append(os.path.dirname(plugins.__file__))
    plugins.__path__ = path
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
    plugins.__path__ = dirs
    for d in dirs:
        if not d:
            continue
        mutter('looking for plugins in %s', d)
        if os.path.isdir(d):
            load_from_dir(d)
        else:
            # it might be a zip: try loading from the zip.
            load_from_zip(d)
            continue


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
        if getattr(plugins, f, None):
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
                warning('Unable to load plugin %r from %r: '
                    'It is not a valid python module name.' % (name, d))
            else:
                warning('Unable to load plugin %r from %r' % (name, d))
            log_exception_quietly()


def load_from_zip(zip_name):
    """Load all the plugins in a zip."""
    valid_suffixes = ('.py', '.pyc', '.pyo')    # only python modules/packages
                                                # is allowed
    if '.zip' not in zip_name:
        return
    try:
        ziobj = zipimport.zipimporter(zip_name)
    except zipimport.ZipImportError:
        # not a valid zip
        return
    mutter('Looking for plugins in %r', zip_name)
    
    import zipfile

    # use zipfile to get list of files/dirs inside zip
    z = zipfile.ZipFile(ziobj.archive)
    namelist = z.namelist()
    z.close()
    
    if ziobj.prefix:
        prefix = ziobj.prefix.replace('\\','/')
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
        if getattr(plugins, plugin_name, None):
            mutter('Plugin name %s already loaded', plugin_name)
            continue
    
        try:
            plugin = ziobj.load_module(plugin_name)
            setattr(plugins, plugin_name, plugin)
            mutter('Load plugin %s from zip %r', plugin_name, zip_name)
        except zipimport.ZipImportError, e:
            mutter('Unable to load plugin %r from %r: %s',
                   plugin_name, zip_name, str(e))
            continue
        except KeyboardInterrupt:
            raise
        except Exception, e:
            ## import pdb; pdb.set_trace()
            warning('Unable to load plugin %r from %r'
                    % (name, zip_name))
            log_exception_quietly()


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
        """Return the modules help topic - its __name__."""
        return self.module.__name__
