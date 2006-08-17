
import os

from bzrlib.config import ConfigObj

from bdlogging import debug
from util import add_ignore


class DebBuildConfig(object):
  """Holds the configuration settings for builddeb. These are taken from
  a hierarchy of config files. .bzr-builddeb/local.conf then 
  ~/.bazaar/builddeb.conf, finally .bzr-builddeb/default.conf. The value is 
  taken from the first file in which it is specified."""

  def __init__(self, localfile=None, globalfile=None, defaultfile=None,
               add_to_ignores=False):
    """ 
    >>> c = DebBuildConfig('local.conf','user.conf','default.conf',False)
    >>> print c.orig_dir()
    None
    >>> print c.merge()
    True
    >>> print c.builder()
    localbuilder
    >>> print c.build_dir()
    defaultbuild
    >>> print c.result_dir()
    userresult
    """
    if globalfile is None:
      globalfile = os.path.expanduser('~/.bazaar/builddeb.conf')
    if localfile is None:
      localfile = ('.bzr-builddeb/local.conf')
    if defaultfile is None:
      defaultfile = ('.bzr-builddeb/default.conf')
    self._config_files = [ConfigObj(localfile), ConfigObj(globalfile), ConfigObj(defaultfile)]
    if add_to_ignores:
      add_ignore(localfile)

  def _get_opt(self, config, key):
    """Returns the value for key from config, of None if it is not defined in 
    the file"""
    try:
      return config.get_value('BUILDDEB', key)
    except KeyError:
      return None

  def _get_best_opt(self, key):
    """Returns the value for key from the first file in which it is defined,
    or None if none of the files define it."""

    for file in self._config_files:
      value = self._get_opt(file, key)
      if value is not None:
        debug("Using %s for %s, taken from %s", value, key, file.filename)
        return value
    return None

  def _get_bool(self, config, key):
    try:
      return True, config.get_bool('BUILDDEB', key)
    except KeyError:
      return False, False

  def _get_best_bool(self, key, default=False):
    for file in self._config_files:
      (found, value) = self._get_bool(file, key)
      if found:
        debug("Using %s for %s, taken from %s", value, key, file.filename)
        return value
    return default

  def build_dir(self):
    return self._get_best_opt('build-dir')

  def orig_dir(self):
    return self._get_best_opt('orig-dir')

  def builder(self):
    return self._get_best_opt('builder')

  def result_dir(self):
    return self._get_best_opt('result-dir')

  def merge(self):
    return self._get_best_bool('merge', False)

  def quick_builder(self):
    return self._get_best_opt('quick-builder')

def _test():
  import doctest
  doctest.testmod()

if __name__ == '__main__':
  _test()

