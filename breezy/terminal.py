# Copyright (C) 2004 Aaron Bentley
# <aaron@aaronbentley.com>
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

"""Terminal color support for Unix terminals.

This module provides utilities for working with colored output in Unix terminals,
including ANSI color codes and helpers for checking terminal capabilities.
"""

__all__ = [
    "color_exists",
    "colorstring",
    "has_ansi_colors",
]

from ._osutils_rs import (
    color_exists,
    colorstring,
    has_ansi_colors,
)


class FG:
    """Unix terminal foreground color codes (16-color)."""

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bold Foreground
    BOLD_RED = "\033[1;31m"
    BOLD_GREEN = "\033[1;32m"
    BOLD_YELLOW = "\033[1;33m"
    BOLD_BLUE = "\033[1;34m"
    BOLD_MAGENTA = "\033[1;35m"
    BOLD_CYAN = "\033[1;36m"
    BOLD_WHITE = "\033[1;37m"

    NONE = "\033[0m"


class BG:
    """Unix terminal background color codes (16-color)."""

    BLACK = "\033[40m"
    RED = "\033[41m"
    GREEN = "\033[42m"
    YELLOW = "\033[43m"
    BLUE = "\033[44m"
    MAGENTA = "\033[45m"
    CYAN = "\033[46m"
    WHITE = "\033[47m"

    NONE = "\033[0m"


def color_string(s, fg, bg=""):
    return fg + bg + s + FG.NONE
