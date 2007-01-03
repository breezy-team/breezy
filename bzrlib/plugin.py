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


"""bzr python plugin support

Any python module in $BZR_PLUGIN_PATH will be imported upon initialization of
bzrlib. The module will be imported as 'bzrlib.plugins.$BASENAME(PLUGIN)'.
In the plugin's main body, it should update any bzrlib registries it wants to
extend; for example, to add new commands, import bzrlib.commands and add your
new command to the plugin_cmds variable.
"""

# TODO: Refactor this to make it more testable.  The main problem at the
# moment is that loading plugins affects the global process state -- for bzr
# in general use it's a reasonable assumption that all plugins are loaded at
# startup and then stay loaded, but this is less good for testing.
# 
# Several specific issues:
#  - plugins can't be unloaded and will continue to effect later tests
#  - load_plugins does nothing if called a second time
#  - plugin hooks can't be removed
#
# Our options are either to remove these restrictions, or work around them by
# loading the plugins into a different space than the one running the tests.
# That could be either a separate Python interpreter or perhaps a new
# namespace inside this interpreter.

import os
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import imp
import types

from bzrlib import (
    config,
    osutils,
    plugins,
    )
""")

from bzrlib.trace import mutter, warning, log_exception_quietly


DEFAULT_PLUGIN_PATH = None


def get_default_plugin_path():
    """Get the DEFAULT_PLUGIN_PATH"""
    global DEFAULT_PLUGIN_PATH
    if DEFAULT_PLUGIN_PATH is None:
        DEFAULT_PLUGIN_PATH = osutils.pathjoin(config.config_dir(), 'plugins')
    return DEFAULT_PLUGIN_PATH


_loaded = False


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

    dirs = os.environ.get('BZR_PLUGIN_PATH',
                          get_default_plugin_path()).split(os.pathsep)
    dirs.insert(0, os.path.dirname(plugins.__file__))

    load_from_dirs(dirs)
    load_from_zips(dirs)


def load_from_dirs(dirs):
    """Load bzrlib plugins found in each dir in dirs.

    Loading a plugin means importing it into the python interpreter.
    The plugin is expected to make calls to register commands when
    it's loaded (or perhaps access other hooks in future.)

    Plugins are loaded into bzrlib.plugins.NAME, and can be found there
    for future reference.
    """
    # Get the list of valid python suffixes for __init__.py?
    # this includes .py, .pyc, and .pyo (depending on if we are running -O)
    # but it doesn't include compiled modules (.so, .dll, etc)
    valid_suffixes = [suffix for suffix, mod_type, flags in imp.get_suffixes()
                              if flags in (imp.PY_SOURCE, imp.PY_COMPILED)]
    package_entries = ['__init__'+suffix for suffix in valid_suffixes]
    for d in dirs:
        if not d:
            continue
        mutter('looking for plugins in %s', d)
        plugin_names = set()
        if not os.path.isdir(d):
            continue
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

        plugin_names = list(plugin_names)
        plugin_names.sort()
        for name in plugin_names:
            try:
                plugin_info = imp.find_module(name, [d])
                # mutter('load plugin %r', plugin_info)
                try:
                    plugin = imp.load_module('bzrlib.plugins.' + name,
                                             *plugin_info)
                    setattr(plugins, name, plugin)
                finally:
                    if plugin_info[0] is not None:
                        plugin_info[0].close()
                # mutter('loaded succesfully')
            except KeyboardInterrupt:
                raise
            except Exception, e:
                ## import pdb; pdb.set_trace()
                warning('Unable to load plugin %r from %r' % (name, d))
                log_exception_quietly()


def load_from_zips(zips):
    """Load bzr plugins from zip archives with zipimport.
    It's similar to load_from_dirs but plugins searched inside archives.
    """
    import zipfile
    import zipimport

    valid_suffixes = ('.py', '.pyc', '.pyo')    # only python modules/packages
                                                # is allowed
    for zip_name in zips:
        if '.zip' not in zip_name:
            continue
        try:
            ziobj = zipimport.zipimporter(zip_name)
        except zipimport.ZipImportError:
            # not a valid zip
            continue
        mutter('Looking for plugins in %r', zip_name)

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
