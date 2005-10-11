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


# This module implements plug-in support.
# Any python module in $BZR_PLUGIN_PATH will be imported upon initialization
# of bzrlib (and then forgotten about).  In the plugin's main body, it should
# update any bzrlib registries it wants to extend; for example, to add new
# commands, import bzrlib.commands and add your new command to the
# plugin_cmds variable.


import os
from bzrlib.config import config_dir
DEFAULT_PLUGIN_PATH = os.path.join(config_dir(), 'plugins')

all_plugins = []
_loaded = False


def load_plugins():
    """
    Find all python plugins and load them.

    Loading a plugin means importing it into the python interpreter.
    The plugin is expected to make calls to register commands when
    it's loaded (or perhaps access other hooks in future.)

    A list of plugs is stored in bzrlib.plugin.all_plugins for future
    reference.

    The environment variable BZR_PLUGIN_PATH is considered a delimited
    set of paths to look through. Each entry is searched for *.py
    files (and whatever other extensions are used in the platform,
    such as *.pyd).
    """

    global all_plugins, _loaded
    if _loaded:
        # People can make sure plugins are loaded, they just won't be twice
        return
        #raise BzrError("plugins already initialized")
    _loaded = True

    import sys, os, imp
    
    from bzrlib.trace import log_error, mutter, log_exception
    from bzrlib.errors import BzrError
    from bzrlib import plugins

    dirs = os.environ.get('BZR_PLUGIN_PATH', DEFAULT_PLUGIN_PATH).split(":")
    dirs.insert(0, os.path.dirname(plugins.__file__))

    # The problem with imp.get_suffixes() is that it doesn't include
    # .pyo which is technically valid
    # It also means that "testmodule.so" will show up as both test and testmodule
    # though it is only valid as 'test'
    # but you should be careful, because "testmodule.py" loads as testmodule.
    suffixes = imp.get_suffixes()
    suffixes.append(('.pyo', 'rb', imp.PY_COMPILED))
    package_entries = ['__init__.py', '__init__.pyc', '__init__.pyo']
    for d in dirs:
        # going through them one by one allows different plugins with the same
        # filename in different directories in the path
        mutter('looking for plugins in %s' % d)
        if not d:
            continue
        plugin_names = set()
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            path = os.path.join(d, f)
            if os.path.isdir(path):
                for entry in package_entries:
                    # This directory should be a package, and thus added to
                    # the list
                    if os.path.isfile(os.path.join(path, entry)):
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
            mutter('add plugin name %s' % f)
            plugin_names.add(f)

        plugin_names = list(plugin_names)
        plugin_names.sort()
        for name in plugin_names:
            try:
                plugin_info = imp.find_module(name, [d])
                mutter('load plugin %r' % (plugin_info,))
                try:
                    plugin = imp.load_module('bzrlib.plugin.' + name,
                                             *plugin_info)
                    all_plugins.append(plugin)
                finally:
                    if plugin_info[0] is not None:
                        plugin_info[0].close()

                mutter('loaded succesfully')
            except:
                log_error('Unable to load plugin %r from %r' % (name, d))
                log_exception()

