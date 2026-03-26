#!/usr/bin/env python3
# Copyright (C) 2024 Jelmer Vernooij
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

"""Version information for dromedary."""

# Version information for dromedary
version_info = (0, 1, 0, "dev", 0)


def _format_version_tuple(version_info):
    """Format version tuple into a version string.

    Args:
        version_info: Tuple of (major, minor, micro, release_type, sub)

    Returns:
        Formatted version string
    """
    if len(version_info) == 2:
        main_version = "%d.%d" % version_info[:2]
    else:
        main_version = "%d.%d.%d" % version_info[:3]
    if len(version_info) <= 3:
        return main_version

    release_type = version_info[3]
    sub = version_info[4]

    if release_type == "final" and sub == 0:
        sub_string = ""
    elif release_type == "final":
        sub_string = "." + str(sub)
    elif release_type == "dev" and sub == 0:
        sub_string = ".dev"
    elif release_type == "dev":
        sub_string = ".dev" + str(sub)
    elif release_type in ("alpha", "beta"):
        if version_info[2] == 0:
            main_version = "%d.%d" % version_info[:2]
        sub_string = "." + release_type[0] + str(sub)
    elif release_type == "candidate":
        sub_string = ".rc" + str(sub)
    else:
        return ".".join(map(str, version_info))

    return main_version + sub_string


__version__ = _format_version_tuple(version_info)
version_string = __version__
