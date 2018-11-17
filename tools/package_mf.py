# Copyright (C) 2008 Canonical Ltd
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

"""Custom module finder for entire package"""

import modulefinder
import os
import sys


class CustomModuleFinder(modulefinder.ModuleFinder):
    """Custom module finder for processing python packages,
    e.g. brz plugins packages.

    :param  path:   list of directories to search for modules;
                    if not specified, python standard library only is used.
    """

    def __init__(self, path=None, debug=0, excludes=[], replace_paths=[]):
        if path is None:
            path = [os.path.dirname(os.__file__)]    # only python std lib
        modulefinder.ModuleFinder.__init__(
            self, path, debug, excludes, replace_paths)

    def run_package(self, package_path):
        """Recursively process each module in package with run_script method.

        :param  package_path:   path to package directory.
        """
        stack = [package_path]
        while stack:
            curdir = stack.pop(0)
            py = os.listdir(curdir)
            for i in py:
                full = os.path.join(curdir, i)
                if os.path.isdir(full):
                    init = os.path.join(full, '__init__.py')
                    if os.path.isfile(init):
                        stack.append(full)
                    continue
                if not i.endswith('.py'):
                    continue
                if i == 'setup.py':     # skip
                    continue
                self.run_script(full)

    def get_result(self):
        """Return 2-tuple: (list of packages, list of modules)"""
        keys = sorted(self.modules.keys())
        mods = []
        packs = []
        for key in keys:
            m = self.modules[key]
            if not m.__file__:      # skip builtins
                continue
            if m.__path__:
                packs.append(key)
            elif key != '__main__':
                mods.append(key)
        return (packs, mods)


if __name__ == '__main__':
    package = sys.argv[1]

    mf = CustomModuleFinder()
    mf.run_package(package)

    packs, mods = mf.get_result()

    print('Packages:')
    print(packs)

    print('Modules:')
    print(mods)
