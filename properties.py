import os

class BuildProperties(object):
  """Properties of this specific build"""

  def __init__(self, changelog, build_dir, tarball_dir, larstiq):
    self._changelog = changelog
    self._build_dir = build_dir
    self._tarball_dir = tarball_dir
    self._larstiq = larstiq
  
  def package(self):
    return self._changelog.package()

  def upstream_version(self):
    return self._changelog.upstream_version()

  def debian_version(self):
    return self._changelog.debian_version()

  def full_version(self):
    return self._changelog.full_version()

  def build_dir(self):
    return self._build_dir

  def source_dir(self):
    return os.path.join(self.build_dir(), 
                        self.package()+"-"+self.full_version())

  def tarball_dir(self):
    return self._tarball_dir

  def larstiq(self):
    return self._larstiq

