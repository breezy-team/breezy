# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Win32-specific helper functions

Only one dependency: ctypes should be installed.
"""

import os
import struct
import sys


# Windows version
if sys.platform == 'win32':
    _major,_minor,_build,_platform,_text = sys.getwindowsversion()
    # from MSDN:
    # dwPlatformId
    #   The operating system platform.
    #   This member can be one of the following values.
    #   ==========================  ======================================
    #   Value                       Meaning
    #   --------------------------  --------------------------------------
    #   VER_PLATFORM_WIN32_NT       The operating system is Windows Vista,
    #   2                           Windows Server "Longhorn",
    #                               Windows Server 2003, Windows XP,
    #                               Windows 2000, or Windows NT.
    #
    #   VER_PLATFORM_WIN32_WINDOWS  The operating system is Windows Me,
    #   1                           Windows 98, or Windows 95.
    #   ==========================  ======================================
    if _platform == 2:
        winver = 'Windows NT'
    else:
        # don't care about real Windows name, just to force safe operations
        winver = 'Windows 98'
else:
    winver = None


# We can cope without it; use a separate variable to help pyflakes
try:
    import ctypes
    has_ctypes = True
except ImportError:
    has_ctypes = False
else:
    if winver == 'Windows 98':
        create_buffer = ctypes.create_string_buffer
        suffix = 'A'
    else:
        create_buffer = ctypes.create_unicode_buffer
        suffix = 'W'


# Special Win32 API constants
# Handles of std streams
WIN32_STDIN_HANDLE = -10
WIN32_STDOUT_HANDLE = -11
WIN32_STDERR_HANDLE = -12

# CSIDL constants (from MSDN 2003)
CSIDL_APPDATA = 0x001A      # Application Data folder
CSIDL_PERSONAL = 0x0005     # My Documents folder

# from winapi C headers
MAX_PATH = 260
UNLEN = 256
MAX_COMPUTERNAME_LENGTH = 31


def get_console_size(defaultx=80, defaulty=25):
    """Return size of current console.

    This function try to determine actual size of current working
    console window and return tuple (sizex, sizey) if success,
    or default size (defaultx, defaulty) otherwise.
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


def get_appdata_location():
    """Return Application Data location.
    Return None if we cannot obtain location.

    Returned value can be unicode or plain sring.
    To convert plain string to unicode use
    s.decode(bzrlib.user_encoding)
    """
    if has_ctypes:
        try:
            SHGetSpecialFolderPath = \
                ctypes.windll.shell32.SHGetSpecialFolderPathW
        except AttributeError:
            pass
        else:
            buf = ctypes.create_unicode_buffer(MAX_PATH)
            if SHGetSpecialFolderPath(None,buf,CSIDL_APPDATA,0):
                return buf.value
    # from env variable
    appdata = os.environ.get('APPDATA')
    if appdata:
        return appdata
    # if we fall to this point we on win98
    # at least try C:/WINDOWS/Application Data
    windir = os.environ.get('windir')
    if windir:
        appdata = os.path.join(windir, 'Application Data')
        if os.path.isdir(appdata):
            return appdata
    # did not find anything
    return None


def get_home_location():
    """Return user's home location.
    Assume on win32 it's the <My Documents> folder.
    If location cannot be obtained return system drive root,
    i.e. C:\

    Returned value can be unicode or plain sring.
    To convert plain string to unicode use
    s.decode(bzrlib.user_encoding)
    """
    if has_ctypes:
        try:
            SHGetSpecialFolderPath = \
                ctypes.windll.shell32.SHGetSpecialFolderPathW
        except AttributeError:
            pass
        else:
            buf = ctypes.create_unicode_buffer(MAX_PATH)
            if SHGetSpecialFolderPath(None,buf,CSIDL_PERSONAL,0):
                return buf.value
    # try for HOME env variable
    home = os.path.expanduser('~')
    if home != '~':
        return home
    # at least return windows root directory
    windir = os.environ.get('windir')
    if windir:
        return os.path.splitdrive(windir)[0] + '/'
    # otherwise C:\ is good enough for 98% users
    return 'C:/'


def get_user_name():
    """Return user name as login name.
    If name cannot be obtained return None.

    Returned value can be unicode or plain sring.
    To convert plain string to unicode use
    s.decode(bzrlib.user_encoding)
    """
    if has_ctypes:
        try:
            advapi32 = ctypes.windll.advapi32
            GetUserName = getattr(advapi32, 'GetUserName'+suffix)
        except AttributeError:
            pass
        else:
            buf = create_buffer(UNLEN+1)
            n = ctypes.c_int(UNLEN+1)
            if GetUserName(buf, ctypes.byref(n)):
                return buf.value
    # otherwise try env variables
    return os.environ.get('USERNAME', None)


def get_host_name():
    """Return host machine name.
    If name cannot be obtained return None.

    Returned value can be unicode or plain sring.
    To convert plain string to unicode use
    s.decode(bzrlib.user_encoding)
    """
    if has_ctypes:
        try:
            kernel32 = ctypes.windll.kernel32
            GetComputerName = getattr(kernel32, 'GetComputerName'+suffix)
        except AttributeError:
            pass
        else:
            buf = create_buffer(MAX_COMPUTERNAME_LENGTH+1)
            n = ctypes.c_int(MAX_COMPUTERNAME_LENGTH+1)
            if GetComputerName(buf, ctypes.byref(n)):
                return buf.value
    # otherwise try env variables
    return os.environ.get('COMPUTERNAME', None)


def _ensure_unicode(s):
    if s and type(s) != unicode:
        import bzrlib
        s = s.decode(bzrlib.user_encoding)
    return s
    

def get_appdata_location_unicode():
    return _ensure_unicode(get_appdata_location())

def get_home_location_unicode():
    return _ensure_unicode(get_home_location())

def get_user_name_unicode():
    return _ensure_unicode(get_user_name())

def get_host_name_unicode():
    return _ensure_unicode(get_host_name())


def glob_expand(file_list):
    """Replacement for glob expansion by the shell.

    Win32's cmd.exe does not do glob expansion (eg ``*.py``), so we do our own
    here.

    :param file_list: A list of filenames which may include shell globs.
    :return: An expanded list of filenames.

    Introduced in bzrlib 0.18.
    """
    if not file_list:
        return []
    import glob
    expanded_file_list = []
    for possible_glob in file_list:
        glob_files = glob.glob(possible_glob)

        if glob_files == []:
            # special case to let the normal code path handle
            # files that do not exists
            expanded_file_list.append(possible_glob)
        else:
            expanded_file_list += glob_files
    expanded_file_list = [_ensure_unicode(elem) for elem in expanded_file_list]
    expanded_file_list = [elem.replace(u'\\', u'/') for elem in expanded_file_list] 
    return expanded_file_list
