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

"""Custom module finder for entire package."""

import contextlib
import os
import sys

# At present, this is only used on Windows (see setup.py)
from py2exe import mf310 as modulefinder


class CustomModuleFinder(modulefinder.ModuleFinder):
    """Custom module finder for processing python packages,
    e.g. brz plugins packages.

    :param  path:   list of directories to search for modules;
                    if not specified, python standard library only is used.
    """

    def __init__(self, path=None, debug=0, excludes=None, replace_paths=None):
        """Initialize the custom module finder.

        Args:
            path (list, optional): List of directories to search for modules.
                                 If not specified, only Python standard library is used.
            debug (int, optional): Debug level for module finder operations. Defaults to 0.
            excludes (list, optional): List of module names to exclude from processing.
                                     Defaults to empty list.
            replace_paths (list, optional): List of path replacements for module locations.
                                          Defaults to empty list.

        Note:
            This initializer sets up the module finder with appropriate defaults
            and delegates to the parent ModuleFinder constructor.
        """
        if excludes is None:
            excludes = []
        if replace_paths is None:
            replace_paths = []
        if path is None:
            path = [os.path.dirname(os.__file__)]  # only python std lib
        modulefinder.ModuleFinder.__init__(self, path, debug, excludes, replace_paths)

    def load_package_recursive(self, fqname):
        """Recursively process each module in package.

        This method loads all modules within a package hierarchy, starting from
        the specified fully qualified package name. It processes all parent
        packages first, then recursively discovers and imports all submodules
        and subpackages, excluding test directories.

        Args:
            fqname (str): Fully qualified name of the package to process.
                         For example: 'breezy.plugins.launchpad'

        Note:
            The method handles import errors gracefully by suppressing exceptions
            during module import operations. It skips 'tests' directories and
            'setup.py' files during recursive discovery.

        Raises:
            KeyError: If a required parent module is not found in the modules dict.
        """
        # Load all the parents
        parent = None
        path = []
        for partname in fqname.split("."):
            parent_path = ".".join(path)
            path.append(partname)
            # import_module works recursively,
            # and some of the dependencies may try
            # to import modules not present on the system.
            # (The actual error is
            # AttributeError: 'NoneType' object has no attribute 'is_package')
            # Ignore errors here and bail out in the collection loop.
            with contextlib.suppress(BaseException):
                self.import_module(
                    partname, ".".join(path), self.modules.get(parent_path, None)
                )
        stack = [(fqname, parent_path)]
        while stack:
            (package, parent_path) = stack.pop(0)
            # Here we assume that all parents have already been imported.
            # Abort when a parent is missing.
            parent = self.modules[parent_path]
            pkg_module = self.import_module(package, package, parent)
            curdir = pkg_module.__file__
            dirlist = os.listdir(curdir)
            for filename in dirlist:
                full = os.path.join(curdir, filename)
                if os.path.isdir(full):
                    if filename == "tests":
                        continue
                    init = os.path.join(full, "__init__.py")
                    if os.path.isfile(init):
                        stack.append((".".join((package, filename)), package))
                    continue
                if not filename.endswith(".py"):
                    continue
                if filename == "setup.py":  # skip
                    continue
                # We only accept .py files, so could use [:-3] too - faster...
                partname = os.path.splitext(filename)[0]
                self.import_module(partname, ".".join((package, partname)), pkg_module)

    def get_result(self):
        """Return discovered packages and modules.

        Analyzes all discovered modules and categorizes them into packages
        and regular modules based on their properties.

        Returns:
            tuple: A 2-tuple containing:
                - list: Sorted list of package names (modules with __path__ attribute)
                - list: Sorted list of module names (regular modules, excluding __main__)

        Note:
            Built-in modules (those without __file__ attribute) are excluded
            from the results. The __main__ module is also excluded from the
            modules list.
        """
        keys = sorted(self.modules.keys())
        mods = []
        packs = []
        for key in keys:
            m = self.modules[key]
            if not m.__file__:  # skip builtins
                continue
            if m.__path__:
                packs.append(key)
            elif key != "__main__":
                mods.append(key)
        return (packs, mods)


if __name__ == "__main__":
    """Command line interface for package module discovery.
    
    Usage: python package_mf.py <package_name>
    
    This script demonstrates the CustomModuleFinder by discovering all
    packages and modules within the specified package and printing them
    to stdout.
    """
    package = sys.argv[1]

    mf = CustomModuleFinder()
    mf.run_package(package)

    packs, mods = mf.get_result()

    print("Packages:")
    print(packs)

    print("Modules:")
    print(mods)
