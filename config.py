#    config.py -- Configuration of bzr-builddeb from files
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
#    
#    This file is part of bzr-builddeb.
#
#    bzr-builldeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import os

from bzrlib.config import ConfigObj
from bzrlib.trace import mutter

from util import add_ignore


class DebBuildConfig(object):
  """Holds the configuration settings for builddeb. These are taken from
  a hierarchy of config files. .bzr-builddeb/local.conf then 
  ~/.bazaar/builddeb.conf, finally .bzr-builddeb/default.conf. The value is 
  taken from the first file in which it is specified."""

  def __init__(self, files=None):
    """ 
    Creates a config to read from config files in a hierarchy.

    Pass it a list of tuples (file, secure, add) where file is the location of
    a config file (that doesn't have to exist, and trusted is True or false,
    and states whether the file can be trusted for sensitive values. Add
    indicates whether the file should be added to .bzrignore if it is not
    already.

    The value will be returned from the first in the list that has it,
    unless that key is marked as needing a trusted file and the file isn't
    trusted.

    If the list is empty then it will be set up the default way for builddeb.

    >>> c = DebBuildConfig([('local.conf', False, False),
    ... ('user.conf', True, False), ('default.conf', False, False)])
    >>> print c.orig_dir
    None
    >>> print c.merge
    True
    >>> print c.export_upstream
    localexport
    >>> print c.build_dir
    defaultbuild
    >>> print c.result_dir
    userresult
    >>> print c.builder
    userbuild
    """
    self._config_files = []
    if files is not None:
      assert(len(files) > 0)
      for input in files:
        if input[2]:
          add_ignore(input[0])
        self._config_files.append((ConfigObj(input[0]), input[1]))
    else:
      globalfile = os.path.expanduser('~/.bazaar/builddeb.conf')
      localfile = ('.bzr-builddeb/local.conf')
      defaultfile = ('.bzr-builddeb/default.conf')
      self._config_files = [(ConfigObj(localfile), False),
                            (ConfigObj(globalfile), True),
                            (ConfigObj(defaultfile), False)]
      add_ignore(localfile)

  def _get_opt(self, config, key):
    """Returns the value for key from config, of None if it is not defined in 
    the file"""
    try:
      return config.get_value('BUILDDEB', key)
    except KeyError:
      return None

  def _get_best_opt(self, key, trusted=False):
    """Returns the value for key, obeying precedence.
    
    Returns the value for the key from the first file in which it is defined,
    or None if none of the files define it.
    
    If trusted is True then the the value will only be taken from a file
    marked as trusted.
    
    """
    for config_file in self._config_files:
      if not trusted or config_file[1]:
        value = self._get_opt(config_file[0], key)
        if value is not None:
          mutter("Using %s for %s, taken from %s", value, key,
                 config_file[0].filename)
          return value
    return None

  def _get_bool(self, config, key):
    try:
      return True, config.get_bool('BUILDDEB', key)
    except KeyError:
      return False, False

  def _get_best_bool(self, key, trusted=False, default=False):
    """Returns the value of key, obeying precedence.

    Returns the value for the key from the first file in which it is defined,
    or default if none of the files define it.
    
    If trusted is True then the the value will only be taken from a file
    marked as trusted.
    
    """
    for config_file in self._config_files:
      if not trusted or config_file[1]:
        (found, value) = self._get_bool(config_file[0], key)
        if found:
          mutter("Using %s for %s, taken from %s", value, key,
                 config_file[0].filename)
          return value
    return default

  def _opt_property(name, help=None, trusted=False):
    return property(lambda self: self._get_best_opt(name, trusted), None,
                    None, help)

  def _bool_property(name, help=None, trusted=False, default=False):
    return property(lambda self: self._get_best_bool(name, trusted, default),
                    None, None, help)

  build_dir = _opt_property('build-dir', "The dir to build in")

  orig_dir = _opt_property('orig-dir', "The dir to get upstream tarballs from")

  builder = _opt_property('builder', "The command to build with", True)

  result_dir = _opt_property('result-dir', "The dir to put the results in")

  merge = _bool_property('merge', "Run in merge mode")

  quick_builder = _opt_property('quick-builder',
                          "A quick command to build with", True)

  source_builder = _opt_property('source-builder',
                          "The command to build source packages with", True)

  ignore_unknowns = _bool_property('ignore-unknowns',
                         "Build even when the tree has unknowns")

  native = _bool_property('native', "Build a native package")

  split = _bool_property('split', "Split a full source package")

  export_upstream = _opt_property('export-upstream',
                         "Get the upstream source from another branch")

  prepull_upstream = _bool_property('export-upstream-prepull',
                         "Pull the upstream branch before exporting it.")

  prepull_upstream_stop = _bool_property('export-upstream-stop-on-trivial-pull',
                         "Stop the build if the upstream pull does nothing.")

def _test():
  import doctest
  doctest.testmod()

if __name__ == '__main__':
  _test()

