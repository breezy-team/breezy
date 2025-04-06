#!/usr/bin/python3

"""Get file version.
Written by Alexander Belchenko, 2006.
"""

import os

import pywintypes  # from pywin32 (http://pywin32.sf.net)
import win32api  # from pywin32 (http://pywin32.sf.net)

__all__ = ["FileNotFound", "VersionNotAvailable", "get_file_version"]
__docformat__ = "restructuredtext"


class FileNotFound(Exception):
    pass


class VersionNotAvailable(Exception):
    pass


def get_file_version(filename):
    """Get file version (windows properties)
    :param  filename:   path to file
    :return:            4-tuple with 4 version numbers.
    """
    if not os.path.isfile(filename):
        raise FileNotFound

    try:
        version_info = win32api.GetFileVersionInfo(filename, "\\")
    except pywintypes.error as err:
        raise VersionNotAvailable from err

    return divmod(version_info["FileVersionMS"], 65536) + divmod(
        version_info["FileVersionLS"], 65536
    )
