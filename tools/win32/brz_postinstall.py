# Copyright (C) 2006, 2007, 2009, 2010 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""brz postinstall helper for win32 installation
Written by Alexander Belchenko

Dependency: ctypes
"""

import os
import shutil
import sys

##
# CONSTANTS

VERSION = "1.5.20070131"

USAGE = """Brz postinstall helper for win32 installation
Usage: %s [options]

OPTIONS:
    -h, --help                  - help message
    -v, --version               - version info

    -n, --dry-run               - print actions rather than execute them
    -q, --silent                - no messages for user

    --start-brz                 - update start_brz.bat
    --add-path                  - add brz directory to environment PATH
    --delete-path               - delete brz directory to environment PATH
    --add-shell-menu            - add shell context menu to start brz session
    --delete-shell-menu         - delete context menu from shell
    --check-mfc71               - check if MFC71.DLL present in system
""" % os.path.basename(sys.argv[0])

# Windows version
_major, _minor, _build, _platform, _text = sys.getwindowsversion()
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
    winver = "Windows NT"
else:
    # don't care about real Windows name, just to force safe operations
    winver = "Windows 98"


##
# INTERNAL VARIABLES

(OK, ERROR) = range(2)
VERSION_FORMAT = "%-50s%s"


def main():
    import ctypes
    import getopt
    import locale
    import re

    import _winreg

    user_encoding = locale.getpreferredencoding() or "ascii"


    hkey_str = {
        _winreg.HKEY_LOCAL_MACHINE: "HKEY_LOCAL_MACHINE",
        _winreg.HKEY_CURRENT_USER: "HKEY_CURRENT_USER",
        _winreg.HKEY_CLASSES_ROOT: "HKEY_CLASSES_ROOT",
    }

    dry_run = False
    silent = False
    start_brz = False
    add_path = False
    delete_path = False
    add_shell_menu = False
    delete_shell_menu = False
    check_mfc71 = False

    try:
        opts, args = getopt.getopt(
            sys.argv[1:],
            "hvnq",
            [
                "help",
                "version",
                "dry-run",
                "silent",
                "start-brz",
                "add-path",
                "delete-path",
                "add-shell-menu",
                "delete-shell-menu",
                "check-mfc71",
            ],
        )

        for o, a in opts:
            if o in ("-h", "--help"):
                print(USAGE)
                return OK
            elif o in ("-v", "--version"):
                print(VERSION_FORMAT % (USAGE.splitlines()[0], VERSION))
                return OK

            elif o in ("-n", "--dry-run"):
                dry_run = True
            elif o in ("-q", "--silent"):
                silent = True

            elif o == "--start-brz":
                start_brz = True
            elif o == "--add-path":
                add_path = True
            elif o == "--delete-path":
                delete_path = True
            elif o == "--add-shell-menu":
                add_shell_menu = True
            elif o == "--delete-shell-menu":
                delete_shell_menu = True
            elif o == "--check-mfc71":
                check_mfc71 = True

    except getopt.GetoptError as msg:
        print(str(msg))
        print(USAGE)
        return ERROR

    # message box from Win32API
    MessageBoxA = ctypes.windll.user32.MessageBoxA
    MB_OK = 0
    MB_ICONERROR = 16
    MB_ICONEXCLAMATION = 48

    brz_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

    if start_brz:
        fname = os.path.join(brz_dir, "start_brz.bat")
        if os.path.isfile(fname):
            with open(fname) as f:
                content = f.readlines()
        else:
            content = ["brz.exe help\n"]

        for ix in xrange(len(content)):
            s = content[ix]
            if re.match(
                r'.*(?<!\\)brz\.exe([ "].*)?$', s.rstrip("\r\n"), re.IGNORECASE
            ):
                content[ix] = s.replace(
                    "brz.exe", '"%s"' % os.path.join(brz_dir, "brz.exe")
                )
            elif s.find(r"C:\Program Files\Breezy") != -1:
                content[ix] = s.replace(r"C:\Program Files\Breezy", brz_dir)

        if dry_run:
            print("*** Write file: start_brz.bat")
            print("*** File content:")
            print("".join(content))
        else:
            with open(fname, "w") as f:
                f.write("".join(content))

    if (add_path or delete_path) and winver == "Windows NT":
        # find appropriate registry key:
        # 1. HKLM\System\CurrentControlSet\Control\SessionManager\Environment
        # 2. HKCU\Environment
        keys = (
            (
                _winreg.HKEY_LOCAL_MACHINE,
                (r"System\CurrentControlSet\Control" r"\Session Manager\Environment"),
            ),
            (_winreg.HKEY_CURRENT_USER, r"Environment"),
        )

        hkey = None
        for key, subkey in keys:
            try:
                hkey = _winreg.OpenKey(key, subkey, 0, _winreg.KEY_ALL_ACCESS)
                try:
                    path_u, type_ = _winreg.QueryValueEx(hkey, "Path")
                except OSError:
                    if key != _winreg.HKEY_CURRENT_USER:
                        _winreg.CloseKey(hkey)
                        hkey = None
                        continue
                    else:
                        path_u = ""
                        type_ = _winreg.REG_SZ
            except OSError:
                continue
            break

        if hkey is None:
            print("Cannot find appropriate registry key for PATH")
        else:
            path_list = [i for i in path_u.split(os.pathsep) if i != ""]
            f_change = False
            for ix, item in enumerate(path_list[:]):
                if item == brz_dir:
                    if delete_path:
                        del path_list[ix]
                        f_change = True
                    elif add_path:
                        print("*** brz already in PATH")
                    break
            else:
                if add_path and not delete_path:
                    path_list.append(brz_dir.decode(user_encoding))
                    f_change = True

            if f_change:
                path_u = os.pathsep.join(path_list)
                if dry_run:
                    print("*** Registry key {}\\{}".format(hkey_str[key], subkey))
                    print("*** Modify PATH variable. New value:")
                    print(path_u)
                else:
                    _winreg.SetValueEx(hkey, "Path", 0, type_, path_u)
                    _winreg.FlushKey(hkey)

        if hkey is not None:
            _winreg.CloseKey(hkey)

    if (add_path or delete_path) and winver == "Windows 98":
        # mutating autoexec.bat
        # adding or delete string:
        # SET PATH=%PATH%;C:\PROGRA~1\Breezy
        abat = "C:\\autoexec.bat"
        abak = "C:\\autoexec.bak"

        def backup_autoexec_bat(name, backupname, dry_run):
            # backup autoexec.bat
            if os.path.isfile(name):
                if not dry_run:
                    shutil.copyfile(name, backupname)
                else:
                    print("*** backup copy of autoexec.bat created")

        GetShortPathName = ctypes.windll.kernel32.GetShortPathNameA
        buf = ctypes.create_string_buffer(260)
        if GetShortPathName(brz_dir, buf, 260):
            brz_dir_8_3 = buf.value
        else:
            brz_dir_8_3 = brz_dir
        pattern = "SET PATH=%PATH%;" + brz_dir_8_3

        # search pattern
        with open(abat) as f:
            lines = f.readlines()
        found = False
        for i in lines:
            if i.rstrip("\r\n") == pattern:
                found = True
                break

        if delete_path and found:
            backup_autoexec_bat(abat, abak, dry_run)
            if not dry_run:
                with open(abat, "w") as f:
                    for i in lines:
                        if i.rstrip("\r\n") != pattern:
                            f.write(i)
            else:
                print("*** Remove line <%s> from autoexec.bat" % pattern)

        elif add_path and not found:
            backup_autoexec_bat(abat, abak, dry_run)
            if not dry_run:
                with open(abat, "a") as f:
                    f.write(pattern)
                    f.write("\n")
            else:
                print("*** Add line <%s> to autoexec.bat" % pattern)

    if add_shell_menu and not delete_shell_menu:
        hkey = None
        try:
            hkey = _winreg.CreateKey(_winreg.HKEY_CLASSES_ROOT, r"Folder\shell\brz")
        except OSError:
            if not silent:
                MessageBoxA(
                    None,
                    "Unable to create registry key for context menu",
                    "EnvironmentError",
                    MB_OK | MB_ICONERROR,
                )

        if hkey is not None:
            _winreg.SetValue(hkey, "", _winreg.REG_SZ, "Brz Here")
            hkey2 = _winreg.CreateKey(hkey, "command")
            _winreg.SetValue(
                hkey2,
                "",
                _winreg.REG_SZ,
                '{} /K "{}"'.format(
                    os.environ.get("COMSPEC", "%COMSPEC%"),
                    os.path.join(brz_dir, "start_brz.bat"),
                ),
            )
            _winreg.CloseKey(hkey2)
            _winreg.CloseKey(hkey)

    if delete_shell_menu:
        try:
            _winreg.DeleteKey(_winreg.HKEY_CLASSES_ROOT, r"Folder\shell\brz\command")
        except OSError:
            pass

        try:
            _winreg.DeleteKey(_winreg.HKEY_CLASSES_ROOT, r"Folder\shell\brz")
        except OSError:
            pass

    if check_mfc71:
        try:
            ctypes.windll.LoadLibrary("mfc71.dll")
        except OSError:
            MessageBoxA(
                None,
                (
                    "Library MFC71.DLL is not found on your system.\n"
                    "This library needed for SFTP transport.\n"
                    "If you need to work via SFTP you should download\n"
                    "this library manually and put it to directory\n"
                    "where Brz installed.\n"
                    "For detailed instructions see:\n"
                    "http://wiki.breezy-vcs.org/OnPureWindows"
                ),
                "Warning",
                MB_OK | MB_ICONEXCLAMATION,
            )

    return OK


if __name__ == "__main__":
    sys.exit(main())
