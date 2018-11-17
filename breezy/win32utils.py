# Copyright (C) 2005-2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Win32-specific helper functions

Only one dependency: ctypes should be installed.
"""

from __future__ import absolute_import

import glob
import operator
import os
import struct
import sys

from breezy import (
    cmdline,
    )
from breezy.i18n import gettext

# We can cope without it; use a separate variable to help pyflakes
try:
    import ctypes
    has_ctypes = True
except ImportError:
    has_ctypes = False
else:
    create_buffer = ctypes.create_unicode_buffer
    extract_buffer = operator.attrgetter("value")
    suffix = 'W'
try:
    import pywintypes
    has_pywintypes = True
except ImportError:
    has_pywintypes = has_win32file = has_win32api = False
else:
    try:
        import win32file
        has_win32file = True
    except ImportError:
        has_win32file = False
    try:
        import win32api
        has_win32api = True
    except ImportError:
        has_win32api = False

# pulling in win32com.shell is a bit of overhead, and normally we don't need
# it as ctypes is preferred and common.  lazy_imports and "optional"
# modules don't work well, so we do our own lazy thing...
has_win32com_shell = None  # Set to True or False once we know for sure...

# Special Win32 API constants
# Handles of std streams
WIN32_STDIN_HANDLE = -10
WIN32_STDOUT_HANDLE = -11
WIN32_STDERR_HANDLE = -12

# CSIDL constants (from MSDN 2003)
CSIDL_APPDATA = 0x001A      # Application Data folder
# <user name>\Local Settings\Application Data (non roaming)
CSIDL_LOCAL_APPDATA = 0x001c
CSIDL_PERSONAL = 0x0005     # My Documents folder

# from winapi C headers
MAX_PATH = 260
UNLEN = 256
MAX_COMPUTERNAME_LENGTH = 31

# Registry data type ids
REG_SZ = 1
REG_EXPAND_SZ = 2


def debug_memory_win32api(message='', short=True):
    """Use trace.note() to dump the running memory info."""
    from breezy import trace
    if has_ctypes:
        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            """Used by GetProcessMemoryInfo"""
            _fields_ = [('cb', ctypes.c_ulong),
                        ('PageFaultCount', ctypes.c_ulong),
                        ('PeakWorkingSetSize', ctypes.c_size_t),
                        ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t),
                        ('PeakPagefileUsage', ctypes.c_size_t),
                        ('PrivateUsage', ctypes.c_size_t),
                        ]
        cur_process = ctypes.windll.kernel32.GetCurrentProcess()
        mem_struct = PROCESS_MEMORY_COUNTERS_EX()
        ret = ctypes.windll.psapi.GetProcessMemoryInfo(
            cur_process, ctypes.byref(mem_struct), ctypes.sizeof(mem_struct))
        if not ret:
            trace.note(gettext('Failed to GetProcessMemoryInfo()'))
            return
        info = {'PageFaultCount': mem_struct.PageFaultCount,
                'PeakWorkingSetSize': mem_struct.PeakWorkingSetSize,
                'WorkingSetSize': mem_struct.WorkingSetSize,
                'QuotaPeakPagedPoolUsage': mem_struct.QuotaPeakPagedPoolUsage,
                'QuotaPagedPoolUsage': mem_struct.QuotaPagedPoolUsage,
                'QuotaPeakNonPagedPoolUsage':
                    mem_struct.QuotaPeakNonPagedPoolUsage,
                'QuotaNonPagedPoolUsage': mem_struct.QuotaNonPagedPoolUsage,
                'PagefileUsage': mem_struct.PagefileUsage,
                'PeakPagefileUsage': mem_struct.PeakPagefileUsage,
                'PrivateUsage': mem_struct.PrivateUsage,
                }
    elif has_win32api:
        import win32process
        # win32process does not return PrivateUsage, because it doesn't use
        # PROCESS_MEMORY_COUNTERS_EX (it uses the one without _EX).
        proc = win32process.GetCurrentProcess()
        info = win32process.GetProcessMemoryInfo(proc)
    else:
        trace.note(gettext('Cannot debug memory on win32 without ctypes'
                           ' or win32process'))
        return
    if short:
        # using base-2 units (see HACKING.txt).
        trace.note(gettext('WorkingSize {0:>7}KiB'
                           '\tPeakWorking {1:>7}KiB\t{2}').format(
                   info['WorkingSetSize'] / 1024,
                   info['PeakWorkingSetSize'] / 1024,
                   message))
        return
    if message:
        trace.note('%s', message)
    trace.note(gettext('WorkingSize       %8d KiB'),
               info['WorkingSetSize'] / 1024)
    trace.note(gettext('PeakWorking       %8d KiB'),
               info['PeakWorkingSetSize'] / 1024)
    trace.note(gettext('PagefileUsage     %8d KiB'),
               info.get('PagefileUsage', 0) / 1024)
    trace.note(gettext('PeakPagefileUsage %8d KiB'),
               info.get('PeakPagefileUsage', 0) / 1024)
    trace.note(gettext('PrivateUsage      %8d KiB'),
               info.get('PrivateUsage', 0) / 1024)
    trace.note(gettext('PageFaultCount    %8d'), info.get('PageFaultCount', 0))


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
    # we need to use stderr instead of stdout
    h = ctypes.windll.kernel32.GetStdHandle(WIN32_STDERR_HANDLE)
    csbi = ctypes.create_string_buffer(22)
    res = ctypes.windll.kernel32.GetConsoleScreenBufferInfo(h, csbi)

    if res:
        (bufx, bufy, curx, cury, wattr,
         left, top, right, bottom, maxx, maxy) = struct.unpack(
            "hhhhHhhhhhh", csbi.raw)
        sizex = right - left + 1
        sizey = bottom - top + 1
        return (sizex, sizey)
    else:
        return (defaultx, defaulty)


def _get_sh_special_folder_path(csidl):
    """Call SHGetSpecialFolderPathW if available, or return None.

    Result is always unicode (or None).
    """
    if has_ctypes:
        try:
            SHGetSpecialFolderPath = \
                ctypes.windll.shell32.SHGetSpecialFolderPathW
        except AttributeError:
            pass
        else:
            buf = ctypes.create_unicode_buffer(MAX_PATH)
            if SHGetSpecialFolderPath(None, buf, csidl, 0):
                return buf.value

    global has_win32com_shell
    if has_win32com_shell is None:
        try:
            from win32com.shell import shell
            has_win32com_shell = True
        except ImportError:
            has_win32com_shell = False
    if has_win32com_shell:
        # still need to bind the name locally, but this is fast.
        from win32com.shell import shell
        try:
            return shell.SHGetSpecialFolderPath(0, csidl, 0)
        except shell.error:
            # possibly E_NOTIMPL meaning we can't load the function pointer,
            # or E_FAIL meaning the function failed - regardless, just ignore it
            pass
    return None


def get_appdata_location():
    """Return Application Data location.
    Return None if we cannot obtain location.

    Windows defines two 'Application Data' folders per user - a 'roaming'
    one that moves with the user as they logon to different machines, and
    a 'local' one that stays local to the machine.  This returns the 'roaming'
    directory, and thus is suitable for storing user-preferences, etc.
    """
    appdata = _get_sh_special_folder_path(CSIDL_APPDATA)
    if appdata:
        return appdata
    # Use APPDATA if defined, will return None if not
    return get_environ_unicode('APPDATA')


def get_local_appdata_location():
    """Return Local Application Data location.
    Return the same as get_appdata_location() if we cannot obtain location.

    Windows defines two 'Application Data' folders per user - a 'roaming'
    one that moves with the user as they logon to different machines, and
    a 'local' one that stays local to the machine.  This returns the 'local'
    directory, and thus is suitable for caches, temp files and other things
    which don't need to move with the user.
    """
    local = _get_sh_special_folder_path(CSIDL_LOCAL_APPDATA)
    if local:
        return local
    # Vista supplies LOCALAPPDATA, but XP and earlier do not.
    local = get_environ_unicode('LOCALAPPDATA')
    if local:
        return local
    return get_appdata_location()


def get_home_location():
    """Return user's home location.
    Assume on win32 it's the <My Documents> folder.
    If location cannot be obtained return system drive root,
    i.e. C:\
    """
    home = _get_sh_special_folder_path(CSIDL_PERSONAL)
    if home:
        return home
    home = get_environ_unicode('HOME')
    if home is not None:
        return home
    homepath = get_environ_unicode('HOMEPATH')
    if homepath is not None:
        return os.path.join(get_environ_unicode('HOMEDIR', ''), home)
    # at least return windows root directory
    windir = get_environ_unicode('WINDIR')
    if windir:
        return os.path.splitdrive(windir)[0] + '/'
    # otherwise C:\ is good enough for 98% users
    return u'C:/'


def get_user_name():
    """Return user name as login name.
    If name cannot be obtained return None.
    """
    if has_ctypes:
        try:
            advapi32 = ctypes.windll.advapi32
            GetUserName = getattr(advapi32, 'GetUserName' + suffix)
        except AttributeError:
            pass
        else:
            buf = create_buffer(UNLEN + 1)
            n = ctypes.c_int(UNLEN + 1)
            if GetUserName(buf, ctypes.byref(n)):
                return extract_buffer(buf)
    # otherwise try env variables
    return get_environ_unicode('USERNAME')


# 1 == ComputerNameDnsHostname, which returns "The DNS host name of the local
# computer or the cluster associated with the local computer."
_WIN32_ComputerNameDnsHostname = 1


def get_host_name():
    """Return host machine name.
    If name cannot be obtained return None.

    :return: A unicode string representing the host name.
    """
    if has_win32api:
        try:
            return win32api.GetComputerNameEx(_WIN32_ComputerNameDnsHostname)
        except (NotImplementedError, win32api.error):
            # NotImplemented will happen on win9x...
            pass
    if has_ctypes:
        try:
            kernel32 = ctypes.windll.kernel32
        except AttributeError:
            pass  # Missing the module we need
        else:
            buf = create_buffer(MAX_COMPUTERNAME_LENGTH + 1)
            n = ctypes.c_int(MAX_COMPUTERNAME_LENGTH + 1)

            # Try GetComputerNameEx which gives a proper Unicode hostname
            GetComputerNameEx = getattr(kernel32, 'GetComputerNameEx' + suffix,
                                        None)
            if (GetComputerNameEx is not None
                and GetComputerNameEx(_WIN32_ComputerNameDnsHostname,
                                      buf, ctypes.byref(n))):
                return extract_buffer(buf)

            # Try GetComputerName in case GetComputerNameEx wasn't found
            # It returns the NETBIOS name, which isn't as good, but still ok.
            # The first GetComputerNameEx might have changed 'n', so reset it
            n = ctypes.c_int(MAX_COMPUTERNAME_LENGTH + 1)
            GetComputerName = getattr(kernel32, 'GetComputerName' + suffix,
                                      None)
            if (GetComputerName is not None
                    and GetComputerName(buf, ctypes.byref(n))):
                return extract_buffer(buf)
    return get_environ_unicode('COMPUTERNAME')


def _ensure_with_dir(path):
    if (not os.path.split(path)[0] or path.startswith(u'*')
            or path.startswith(u'?')):
        return u'./' + path, True
    else:
        return path, False


def _undo_ensure_with_dir(path, corrected):
    if corrected:
        return path[2:]
    else:
        return path


def glob_one(possible_glob):
    """Same as glob.glob().

    work around bugs in glob.glob()
    - Python bug #1001604 ("glob doesn't return unicode with ...")
    - failing expansion for */* with non-iso-8859-* chars
    """
    corrected_glob, corrected = _ensure_with_dir(possible_glob)
    glob_files = glob.glob(corrected_glob)

    if not glob_files:
        # special case to let the normal code path handle
        # files that do not exist, etc.
        glob_files = [possible_glob]
    elif corrected:
        glob_files = [_undo_ensure_with_dir(elem, corrected)
                      for elem in glob_files]
    return [elem.replace(u'\\', u'/') for elem in glob_files]


def glob_expand(file_list):
    """Replacement for glob expansion by the shell.

    Win32's cmd.exe does not do glob expansion (eg ``*.py``), so we do our own
    here.

    :param file_list: A list of filenames which may include shell globs.
    :return: An expanded list of filenames.

    Introduced in breezy 0.18.
    """
    if not file_list:
        return []
    expanded_file_list = []
    for possible_glob in file_list:
        expanded_file_list.extend(glob_one(possible_glob))
    return expanded_file_list


def get_app_path(appname):
    r"""Look up in Windows registry for full path to application executable.
    Typically, applications create subkey with their basename
    in HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\

    :param  appname:    name of application (if no filename extension
                        is specified, .exe used)
    :return:    full path to aplication executable from registry,
                or appname itself if nothing found.
    """
    import _winreg

    basename = appname
    if not os.path.splitext(basename)[1]:
        basename = appname + '.exe'

    try:
        hkey = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE,
                               'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\' +
                               basename)
    except EnvironmentError:
        return appname

    try:
        try:
            path, type_id = _winreg.QueryValueEx(hkey, '')
        except WindowsError:
            return appname
    finally:
        _winreg.CloseKey(hkey)

    if type_id == REG_SZ:
        return path
    if type_id == REG_EXPAND_SZ and has_win32api:
        fullpath = win32api.ExpandEnvironmentStrings(path)
        if len(fullpath) > 1 and fullpath[0] == '"' and fullpath[-1] == '"':
            fullpath = fullpath[1:-1]   # remove quotes around value
        return fullpath
    return appname


def set_file_attr_hidden(path):
    """Set file attributes to hidden if possible"""
    if has_win32file:
        SetFileAttributes = win32file.SetFileAttributesW
        try:
            SetFileAttributes(path, win32file.FILE_ATTRIBUTE_HIDDEN)
        except pywintypes.error as e:
            from . import trace
            trace.mutter('Unable to set hidden attribute on %r: %s', path, e)


def _command_line_to_argv(command_line, argv, single_quotes_allowed=False):
    """Convert a Unicode command line into a list of argv arguments.

    It performs wildcard expansion to make wildcards act closer to how they
    work in posix shells, versus how they work by default on Windows. Quoted
    arguments are left untouched.

    :param command_line: The unicode string to split into an arg list.
    :param single_quotes_allowed: Whether single quotes are accepted as quoting
                                  characters like double quotes. False by
                                  default.
    :return: A list of unicode strings.
    """
    # First, split the command line
    s = cmdline.Splitter(
        command_line, single_quotes_allowed=single_quotes_allowed)

    # Bug #587868 Now make sure that the length of s agrees with sys.argv
    # we do this by simply counting the number of arguments in each. The counts should
    # agree no matter what encoding sys.argv is in (AFAIK)
    # len(arguments) < len(sys.argv) should be an impossibility since python gets
    # args from the very same PEB as does GetCommandLineW
    arguments = list(s)

    # Now shorten the command line we get from GetCommandLineW to match sys.argv
    if len(arguments) < len(argv):
        raise AssertionError("Split command line can't be shorter than argv")
    arguments = arguments[len(arguments) - len(argv):]

    # Carry on to process globs (metachars) in the command line
    # expand globs if necessary
    # TODO: Use 'globbing' instead of 'glob.glob', this gives us stuff like
    #       '**/' style globs
    args = []
    for is_quoted, arg in arguments:
        if is_quoted or not glob.has_magic(arg):
            args.append(arg)
        else:
            args.extend(glob_one(arg))
    return args


if has_ctypes:
    def get_unicode_argv():
        prototype = ctypes.WINFUNCTYPE(ctypes.c_wchar_p)
        GetCommandLineW = prototype(("GetCommandLineW",
                                     ctypes.windll.kernel32))
        command_line = GetCommandLineW()
        if command_line is None:
            raise ctypes.WinError()
        # Skip the first argument, since we only care about parameters
        argv = _command_line_to_argv(command_line, sys.argv)[1:]
        return argv

    def get_environ_unicode(key, default=None):
        """Get `key` from environment as unicode or `default` if unset

        The environment is natively unicode on modern windows versions but
        Python 2 only accesses it through the legacy bytestring api.

        Environmental variable names are case insenstive on Windows.

        A large enough buffer will be allocated to retrieve the value, though
        it may take two calls to the underlying library function.

        This needs ctypes because pywin32 does not expose the wide version.
        """
        cfunc = getattr(get_environ_unicode, "_c_function", None)
        if cfunc is None:
            from ctypes.wintypes import DWORD, LPCWSTR, LPWSTR
            cfunc = ctypes.WINFUNCTYPE(DWORD, LPCWSTR, LPWSTR, DWORD)(
                ("GetEnvironmentVariableW", ctypes.windll.kernel32))
            get_environ_unicode._c_function = cfunc
        buffer_size = 256  # heuristic, 256 characters often enough
        while True:
            buffer = ctypes.create_unicode_buffer(buffer_size)
            length = cfunc(key, buffer, buffer_size)
            if not length:
                code = ctypes.GetLastError()
                if code == 203:  # ERROR_ENVVAR_NOT_FOUND
                    return default
                raise ctypes.WinError(code)
            if buffer_size > length:
                return buffer[:length]
            buffer_size = length


if has_win32api:
    def _pywin32_is_local_pid_dead(pid):
        """True if pid doesn't correspond to live process on this machine"""
        try:
            handle = win32api.OpenProcess(1, False, pid)  # PROCESS_TERMINATE
        except pywintypes.error as e:
            if e[0] == 5:  # ERROR_ACCESS_DENIED
                # Probably something alive we're not allowed to kill
                return False
            elif e[0] == 87:  # ERROR_INVALID_PARAMETER
                return True
            raise
        handle.close()
        return False
    is_local_pid_dead = _pywin32_is_local_pid_dead
elif has_ctypes and sys.platform == 'win32':
    from ctypes.wintypes import BOOL, DWORD, HANDLE
    _kernel32 = ctypes.windll.kernel32
    _CloseHandle = ctypes.WINFUNCTYPE(BOOL, HANDLE)(
        ("CloseHandle", _kernel32))
    _OpenProcess = ctypes.WINFUNCTYPE(HANDLE, DWORD, BOOL, DWORD)(
        ("OpenProcess", _kernel32))

    def _ctypes_is_local_pid_dead(pid):
        """True if pid doesn't correspond to live process on this machine"""
        handle = _OpenProcess(1, False, pid)  # PROCESS_TERMINATE
        if not handle:
            errorcode = ctypes.GetLastError()
            if errorcode == 5:  # ERROR_ACCESS_DENIED
                # Probably something alive we're not allowed to kill
                return False
            elif errorcode == 87:  # ERROR_INVALID_PARAMETER
                return True
            raise ctypes.WinError(errorcode)
        _CloseHandle(handle)
        return False
    is_local_pid_dead = _ctypes_is_local_pid_dead


def _is_pywintypes_error(evalue):
    """True if exception instance is an error from pywin32"""
    if has_pywintypes and isinstance(evalue, pywintypes.error):
        return True
    return False
