# Copyright (C) 2004, 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

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

import imp
import os
import sys
import types

import bzrlib
from bzrlib.config import config_dir
from bzrlib.trace import log_error, mutter, log_exception, warning, \
        log_exception_quietly
from bzrlib.errors import BzrError
from bzrlib import plugins
from bzrlib.osutils import pathjoin

DEFAULT_PLUGIN_PATH = pathjoin(config_dir(), 'plugins')

_loaded = False


def all_plugins():
    """Return a dictionary of the plugins."""
    result = {}
    for name, plugin in bzrlib.plugins.__dict__.items():
        if isinstance(plugin, types.ModuleType):
            result[name] = plugin
    return result


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
        #raise BzrError("plugins already initialized")
    _loaded = True

    dirs = os.environ.get('BZR_PLUGIN_PATH', DEFAULT_PLUGIN_PATH).split(os.pathsep)
    dirs.insert(0, os.path.dirname(plugins.__file__))

    load_from_dirs(dirs)


def load_from_dirs(dirs):
    """Load bzrlib plugins found in each dir in dirs.

    Loading a plugin means importing it into the python interpreter.
    The plugin is expected to make calls to register commands when
    it's loaded (or perhaps access other hooks in future.)

    Plugins are loaded into bzrlib.plugins.NAME, and can be found there
    for future reference.
    """
    # The problem with imp.get_suffixes() is that it doesn't include
    # .pyo which is technically valid
    # It also means that "testmodule.so" will show up as both test and testmodule
    # though it is only valid as 'test'
    # but you should be careful, because "testmodule.py" loads as testmodule.
    suffixes = imp.get_suffixes()
    suffixes.append(('.pyo', 'rb', imp.PY_COMPILED))
    package_entries = ['__init__.py', '__init__.pyc', '__init__.pyo']
    for d in dirs:
        if not d:
            continue
        mutter('looking for plugins in %s', d)
        plugin_names = set()
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            path = pathjoin(d, f)
            if os.path.isdir(path):
                for entry in package_entries:
                    # This directory should be a package, and thus added to
                    # the list
                    if os.path.isfile(pathjoin(path, entry)):
                        break
                else: # This directory is not a package
                    continue
            else:
                for suffix_info in suffixes:
                    if f.endswith(suffix_info[0]):
                        f = f[:-len(suffix_info[0])]
                        if suffix_info[2] == imp.C_EXTENSION and f.endswith('module'):
                            f = f[:-len('module')]
                        break
                else:
                    continue
            if getattr(bzrlib.plugins, f, None):
                mutter('Plugin name %s already loaded', f)
            else:
                mutter('add plugin name %s', f)
                plugin_names.add(f)

        plugin_names = list(plugin_names)
        plugin_names.sort()
        for name in plugin_names:
            try:
                plugin_info = imp.find_module(name, [d])
                mutter('load plugin %r', plugin_info)
                try:
                    plugin = imp.load_module('bzrlib.plugins.' + name,
                                             *plugin_info)
                    setattr(bzrlib.plugins, name, plugin)
                finally:
                    if plugin_info[0] is not None:
                        plugin_info[0].close()

                mutter('loaded succesfully')
            except KeyboardInterrupt:
                raise
            except Exception, e:
                ## import pdb; pdb.set_trace()
                warning('Unable to load plugin %r from %r' % (name, d))
                log_exception_quietly()
