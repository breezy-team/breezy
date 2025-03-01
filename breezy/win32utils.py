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

"""Win32-specific helper functions."""

import glob
import os
import struct

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
import ctypes

from breezy import cmdline
from breezy.i18n import gettext
""",
)


# Special Win32 API constants
# Handles of std streams
WIN32_STDIN_HANDLE = -10
WIN32_STDOUT_HANDLE = -11
WIN32_STDERR_HANDLE = -12

# CSIDL constants (from MSDN 2003)
CSIDL_APPDATA = 0x001A  # Application Data folder
# <user name>\Local Settings\Application Data (non roaming)
CSIDL_LOCAL_APPDATA = 0x001C
CSIDL_PERSONAL = 0x0005  # My Documents folder

# from winapi C headers
MAX_PATH = 260
UNLEN = 256
MAX_COMPUTERNAME_LENGTH = 31

# Registry data type ids
REG_SZ = 1
REG_EXPAND_SZ = 2


def debug_memory_win32api(message="", short=True):
    """Use trace.note() to dump the running memory info."""
    from breezy import trace

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        """Used by GetProcessMemoryInfo."""

        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    cur_process = ctypes.windll.kernel32.GetCurrentProcess()
    mem_struct = PROCESS_MEMORY_COUNTERS_EX()
    ret = ctypes.windll.psapi.GetProcessMemoryInfo(
        cur_process, ctypes.byref(mem_struct), ctypes.sizeof(mem_struct)
    )
    if not ret:
        trace.note(gettext("Failed to GetProcessMemoryInfo()"))
        return
    info = {
        "PageFaultCount": mem_struct.PageFaultCount,
        "PeakWorkingSetSize": mem_struct.PeakWorkingSetSize,
        "WorkingSetSize": mem_struct.WorkingSetSize,
        "QuotaPeakPagedPoolUsage": mem_struct.QuotaPeakPagedPoolUsage,
        "QuotaPagedPoolUsage": mem_struct.QuotaPagedPoolUsage,
        "QuotaPeakNonPagedPoolUsage": mem_struct.QuotaPeakNonPagedPoolUsage,
        "QuotaNonPagedPoolUsage": mem_struct.QuotaNonPagedPoolUsage,
        "PagefileUsage": mem_struct.PagefileUsage,
        "PeakPagefileUsage": mem_struct.PeakPagefileUsage,
        "PrivateUsage": mem_struct.PrivateUsage,
    }
    if short:
        # using base-2 units (see HACKING.txt).
        trace.note(
            gettext("WorkingSize {0:>7}KiB\tPeakWorking {1:>7}KiB\t{2}").format(
                info["WorkingSetSize"] / 1024,
                info["PeakWorkingSetSize"] / 1024,
                message,
            )
        )
        return
    if message:
        trace.note("%s", message)
    trace.note(gettext("WorkingSize       %8d KiB"), info["WorkingSetSize"] / 1024)
    trace.note(gettext("PeakWorking       %8d KiB"), info["PeakWorkingSetSize"] / 1024)
    trace.note(
        gettext("PagefileUsage     %8d KiB"), info.get("PagefileUsage", 0) / 1024
    )
    trace.note(
        gettext("PeakPagefileUsage %8d KiB"), info.get("PeakPagefileUsage", 0) / 1024
    )
    trace.note(gettext("PrivateUsage      %8d KiB"), info.get("PrivateUsage", 0) / 1024)
    trace.note(gettext("PageFaultCount    %8d"), info.get("PageFaultCount", 0))


def get_console_size(defaultx=80, defaulty=25):
    """Return size of current console.

    This function try to determine actual size of current working
    console window and return tuple (sizex, sizey) if success,
    or default size (defaultx, defaulty) otherwise.
    """
    # To avoid problem with redirecting output via pipe
    # we need to use stderr instead of stdout
    h = ctypes.windll.kernel32.GetStdHandle(WIN32_STDERR_HANDLE)
    csbi = ctypes.create_string_buffer(22)
    res = ctypes.windll.kernel32.GetConsoleScreenBufferInfo(h, csbi)

    if res:
        (bufx, bufy, curx, cury, wattr, left, top, right, bottom, maxx, maxy) = (
            struct.unpack("hhhhHhhhhhh", csbi.raw)
        )
        sizex = right - left + 1
        sizey = bottom - top + 1
        return (sizex, sizey)
    else:
        return (defaultx, defaulty)


def _get_sh_special_folder_path(csidl):
    """Call SHGetSpecialFolderPathW if available, or return None.

    Result is always unicode (or None).
    """
    try:
        SHGetSpecialFolderPath = ctypes.windll.shell32.SHGetSpecialFolderPathW
    except AttributeError:
        pass
    else:
        buf = ctypes.create_unicode_buffer(MAX_PATH)
        if SHGetSpecialFolderPath(None, buf, csidl, 0):
            return buf.value


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
    return os.environ.get("APPDATA")


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
    local = os.environ.get("LOCALAPPDATA")
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
    home = os.environ.get("HOME")
    if home is not None:
        return home
    homepath = os.environ.get("HOMEPATH")
    if homepath is not None:
        return os.path.join(os.environ.get("HOMEDIR", ""), home)
    # at least return windows root directory
    windir = os.environ.get("WINDIR")
    if windir:
        return os.path.splitdrive(windir)[0] + "/"
    # otherwise C:\ is good enough for 98% users
    return "C:/"


def get_user_name():
    """Return user name as login name.
    If name cannot be obtained return None.
    """
    try:
        advapi32 = ctypes.windll.advapi32
        GetUserName = advapi32.GetUserNameW
    except AttributeError:
        pass
    else:
        buf = ctypes.create_unicode_buffer(UNLEN + 1)
        n = ctypes.c_int(UNLEN + 1)
        if GetUserName(buf, ctypes.byref(n)):
            return buf.value
    # otherwise try env variables
    return os.environ.get("USERNAME")


# 1 == ComputerNameDnsHostname, which returns "The DNS host name of the local
# computer or the cluster associated with the local computer."
_WIN32_ComputerNameDnsHostname = 1


def get_host_name():
    """Return host machine name.
    If name cannot be obtained return None.

    :return: A unicode string representing the host name.
    """
    buf = ctypes.create_unicode_buffer(MAX_COMPUTERNAME_LENGTH + 1)
    n = ctypes.c_int(MAX_COMPUTERNAME_LENGTH + 1)

    # Try GetComputerNameEx which gives a proper Unicode hostname
    GetComputerNameEx = getattr(ctypes.windll.kernel32, "GetComputerNameExW", None)
    if GetComputerNameEx is not None and GetComputerNameEx(
        _WIN32_ComputerNameDnsHostname, buf, ctypes.byref(n)
    ):
        return buf.value
    return os.environ.get("COMPUTERNAME")


def _ensure_with_dir(path):
    if not os.path.split(path)[0] or path.startswith("*") or path.startswith("?"):
        return "./" + path, True
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
        glob_files = [_undo_ensure_with_dir(elem, corrected) for elem in glob_files]
    return [elem.replace("\\", "/") for elem in glob_files]


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
    import winreg

    basename = appname
    if not os.path.splitext(basename)[1]:
        basename = appname + ".exe"

    try:
        hkey = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + basename,
        )
    except OSError:
        return appname

    try:
        try:
            path, type_id = winreg.QueryValueEx(hkey, "")
        except OSError:
            return appname
    finally:
        winreg.CloseKey(hkey)

    if type_id == REG_SZ:
        return path
    return appname


def set_file_attr_hidden(path):
    """Set file attributes to hidden if possible."""
    from ctypes.wintypes import BOOL, DWORD, LPWSTR

    # <https://docs.microsoft.com/windows/desktop/api/fileapi/nf-fileapi-setfileattributesw>
    SetFileAttributes = ctypes.windll.kernel32.SetFileAttributesW
    SetFileAttributes.argtypes = LPWSTR, DWORD
    SetFileAttributes.restype = BOOL
    FILE_ATTRIBUTE_HIDDEN = 2
    if not SetFileAttributes(path, FILE_ATTRIBUTE_HIDDEN):
        e = ctypes.WinError()
        from . import trace

        trace.mutter("Unable to set hidden attribute on %r: %s", path, e)


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
    s = cmdline.Splitter(command_line, single_quotes_allowed=single_quotes_allowed)

    # Bug #587868 Now make sure that the length of s agrees with sys.argv
    # we do this by simply counting the number of arguments in each. The counts should
    # agree no matter what encoding sys.argv is in (AFAIK)
    # len(arguments) < len(sys.argv) should be an impossibility since python gets
    # args from the very same PEB as does GetCommandLineW
    arguments = list(s)

    # Now shorten the command line we get from GetCommandLineW to match sys.argv
    if len(arguments) < len(argv):
        raise AssertionError("Split command line can't be shorter than argv")
    arguments = arguments[len(arguments) - len(argv) :]

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


def _ctypes_is_local_pid_dead(pid):
    """True if pid doesn't correspond to live process on this machine."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(1, False, pid)
    if not handle:
        errorcode = ctypes.GetLastError()
        if errorcode == 5:  # ERROR_ACCESS_DENIED
            # Probably something alive we're not allowed to kill
            return False
        elif errorcode == 87:  # ERROR_INVALID_PARAMETER
            return True
        raise ctypes.WinError(errorcode)
    kernel32.CloseHandle(handle)
    return False


is_local_pid_dead = _ctypes_is_local_pid_dead


def get_fs_type(drive):
    r"""Return file system type for a drive on the system.

    Args:
      drive: Unicode string with drive including trailing backslash (e.g.
         "C:\\")

    Returns:
      Windows filesystem type name (e.g. "FAT32", "NTFS") or None
      if the drive can not be found
    """
    MAX_FS_TYPE_LENGTH = 16
    kernel32 = ctypes.windll.kernel32
    GetVolumeInformation = kernel32.GetVolumeInformationW
    fs_type = ctypes.create_unicode_buffer(MAX_FS_TYPE_LENGTH + 1)
    if GetVolumeInformation(
        drive,
        None,
        0,  # lpVolumeName
        None,  # lpVolumeSerialNumber
        None,  # lpMaximumComponentLength
        None,  # lpFileSystemFlags
        fs_type,
        MAX_FS_TYPE_LENGTH,
    ):
        return fs_type.value
    return None
