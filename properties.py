#    properties.py -- Properties of a build
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006 James Westby <jw+debian@jameswestby.net>
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

