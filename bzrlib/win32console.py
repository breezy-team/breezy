# Copyright (C) 2006 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""
Set of functions to work with console on Windows.
Author: Alexander Belchenko (e-mail: bialix AT ukr.net)
License: Public domain
"""

import struct

# We can cope without it; use a separate variable to help pyflakes
try:
   import ctypes
   has_ctypes = True
except ImportError:
    has_ctypes = False


WIN32_STDIN_HANDLE = -10
WIN32_STDOUT_HANDLE = -11
WIN32_STDERR_HANDLE = -12


def get_console_size(defaultx=80, defaulty=25):
   """ Return size of current console.

   This function try to determine actual size of current working
   console window and return tuple (sizex, sizey) if success,
   or default size (defaultx, defaulty) otherwise.

   Dependencies: ctypes should be installed.
   """
   if not has_ctypes:
       # no ctypes is found
       return (defaultx, defaulty)

   # To avoid problem with redirecting output via pipe
   # need to use stderr instead of stdout
   h = ctypes.windll.kernel32.GetStdHandle(WIN32_STDERR_HANDLE)
   csbi = ctypes.create_string_buffer(22)
   res = ctypes.windll.kernel32.GetConsoleScreenBufferInfo(h, csbi)

   if res:
       (bufx, bufy, curx, cury, wattr,
        left, top, right, bottom, maxx, maxy) = struct.unpack("hhhhHhhhhhh", csbi.raw)
       sizex = right - left + 1
       sizey = bottom - top + 1
       return (sizex, sizey)
   else:
       return (defaultx, defaulty)
