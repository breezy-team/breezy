#    repack_tarball.py -- Repack files/dirs in to tarballs.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
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

import gzip
import os
import shutil
import tarfile
import zipfile

from bzrlib.errors import (NoSuchFile,
                           FileExists,
                           )


def repack_tarball(orig_name, new_name):
  """Repack the file/dir named to a .tar.gz with the chosen name.

  This function takes a named file of either .tar.gz, .tar .tgz .tar.bz2 
  or .zip type, or a directory, and creates the file named in the second
  argument in .tar.gz format.

  The source must exist, and the target cannot exist.
  
  :param orig_name: the curent name of the file/dir
  :type orig_name: string
  :param new_name: the desired name of the tarball
  :type new_name: string
  :return: None
  :warning: .zip files are currently unsupported.
  """
  if not os.path.exists(orig_name):
    raise NoSuchFile(orig_name)
  if os.path.exists(new_name):
    raise FileExists(new_name)
  if os.path.isdir(orig_name):
    tar = tarfile.open(new_name, 'w:gz')
    try:
      tar.add(orig_name, os.path.basename(orig_name))
    finally:
      tar.close()
  else:
    if orig_name.endswith('.tar.gz') or orig_name.endswith('.tgz'):
      shutil.copyfile(orig_name, new_name)
    elif orig_name.endswith('.tar'):
      f = open(orig_name)
      try:
        gz = gzip.GzipFile(new_name, 'w')
        try:
          gz.write(f.read())
        finally:
          gz.close()
      finally:
        f.close()
    elif orig_name.endswith('.tar.bz2'):
      old_tar = tarfile.open(orig_name, 'r:bz2')
      try:
        new_tar = tarfile.open(new_name, 'w:gz')
        try:
          for old_member in old_tar.getmembers():
            new_tar.addfile(old_member)
        finally:
          new_tar.close()
      finally:
        old_tar.close()
  # TODO: handle zip files.
  # TODO: complain on unrecognised formats and test for that.

