
import os

from debian_bundle import deb822

from logging import debug

class DebianChanges(deb822.changes):
  """Abstraction of the .changes file. Use it to find out what files were 
  built."""

  def __init__(self, package, version, dir):
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


