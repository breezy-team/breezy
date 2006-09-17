#    changes.py -- Abstraction of .changes files
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

import commands
import os

from debian_bundle import deb822

from bdlogging import debug
from errors import DebianError

class DebianChanges(deb822.Changes):
  """Abstraction of the .changes file. Use it to find out what files were 
  built."""

  def __init__(self, package, version, dir, arch=None):
    """
    >>> c = DebianChanges('bzr-builddeb', '0.1-1', None, 'i386')
    >>> fs = c.files()
    >>> f = fs[0]
    >>> f['name']
    'bzr-builddeb_0.1-1.dsc'
    >>> f['priority']
    'optional'
    >>> f['section']
    'devel'
    >>> f['size']
    '290'
    >>> f['md5sum']
    'b4c9b646c741f531dd8349db83c77cae'
    """
    if arch is None:
      status, arch = commands.getstatusoutput(
          'dpkg-architecture -qDEB_BUILD_ARCH')
      if status > 0:
        raise DebianError("Could not find the build architecture")
    changes = str(package)+"_"+str(version)+"_"+str(arch)+".changes"
    if dir is not None:
      changes = os.path.join(dir,changes)
    debug("Looking for %s", changes)    
    if not os.path.exists(changes):
      raise DebianError("Could not find "+package)
    fp = open(changes)
    super(DebianChanges, self).__init__(fp)
    self._filename = changes
    
  def files(self):
    return self['Files']

  def filename(self):
    return self._filename


def _test():
  import doctest
  doctest.testmod()

if __name__ == "__main__":
  _test()
  
