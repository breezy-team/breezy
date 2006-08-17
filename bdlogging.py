#    bdlogging.py -- Logging facilites
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

from bzrlib.trace import info as bzrinfo, mutter as bzrmutter

verbose = False

def set_verbose(v):
  verbose=v
  
def debug(fmt, *args):
  """Log a message that will be shown if verbose is on."""
  if verbose:
    bzrinfo(fmt, *args)
  else:
    bzrmutter(fmt, *args)

def info(fmt, *args):
  bzrinfo(fmt, *args)

def _test():
  import doctest
  doctest.testmod()

if __name__ == "__main__":
  _test()


