# Copyright (C) 2004 Aaron Bentley
# <aaron@aaronbentley.com>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os
import sys

__docformat__ = "restructuredtext"
__doc__ = "Terminal control functionality"

def has_ansi_colors():
    # XXX The whole color handling should be rewritten to use terminfo
    # XXX before we get there, checking for setaf capability should do.
    # XXX See terminfo(5) for all the gory details.
    if sys.platform == "win32":
        return False
    if not sys.stdout.isatty():
        return False
    import curses
    try:
        curses.setupterm()
    except curses.error:
        return False
    return bool(curses.tigetstr('setaf'))

colors = {
"black": "0",
"red": "1",
"green": "2",
"yellow": "3",
"blue": "4",
"magenta": "5",
"cyan": "6",
"white": "7"
}

def colorstring(text, fgcolor=None, bgcolor=None):
    """
    Returns a string using ANSI control codes to set the text color.

    :param text: The text to set the color for.
    :type text: string
    :param fgcolor: The foreground color to use
    :type fgcolor: string
    :param bgcolor: The background color to use
    :type bgcolor: string
    """
    code = []

    if fgcolor:
        if fgcolor.startswith('dark'):
            code.append('0')
            fgcolor = fgcolor[4:]
        else:
            code.append('1')

        code.append('3' + colors[fgcolor])

    if bgcolor:
        code.append('4' + colors[bgcolor])

    return "".join(("\033[", ';'.join(code), "m", text, "\033[0m"))


def term_title(title):
    term = os.environ.get('TERM', '')
    if term.startswith('xterm') or term == 'dtterm':
        return "\033]0;%s\007" % title
    return str()


# arch-tag: a79b9993-146e-4a51-8bae-a13791703ddd
