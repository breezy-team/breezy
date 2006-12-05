#    errors.py -- Error classes
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

from bzrlib.errors import BzrError


class DebianError(BzrError):
  _fmt = """A Debian packaging error occured: %(message)s"""

  def __init__(self, message):
    BzrError.__init__(self)
    self.message = message

class ChangedError(DebianError):
  _fmt = """There are modified files in the working tree. Either commit the 
  changes, use --working to build the working tree, or --ignore-changes
  to override this and build the branch without the changes in the working 
  tree. Use bzr status to see the changes"""

  def __init__(self):
    DebianError.__init__(self, None)

class NoSourceDirError(DebianError):
  _fmt = """There is no existing source directory to use. Use --export-only or 
  --dont-purge to get one that can be used"""

  def __init__(self):
    DebianError.__init__(self, None)

class NotInBaseError(BzrError):
  _fmt = """Must be invoked from the base of a branch."""
  def __init__(self):
    BzrError.__init__(self)

class BuildFailedError(DebianError):
  _fmt = """The build failed."""
  def __init__(self):
    DebianError.__init__(self, None)

