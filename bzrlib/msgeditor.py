# Bazaar-NG -- distributed version control

# Copyright (C) 2005 by Canonical Ltd

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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Commit message editor support."""

import os
from subprocess import call

import bzrlib.config as config
from bzrlib.errors import BzrError

def _get_editor():
    """Return a sequence of possible editor binaries for the current platform"""
    try:
        yield os.environ["BZR_EDITOR"]
    except KeyError:
        pass

    e = config.GlobalConfig().get_editor()
    if e is not None:
        yield e
        
    try:
        yield os.environ["EDITOR"]
    except KeyError:
        pass

    if os.name == "nt":
        yield "notepad.exe"
    elif os.name == "posix":
        yield "/usr/bin/vi"


def _run_editor(filename):
    """Try to execute an editor to edit the commit message."""
    for e in _get_editor():
        edargs = e.split(' ')
        x = call(edargs + [filename])
        if x == 0:
            return True
        elif x == 127:
            continue
        else:
            break
    raise BzrError("Could not start any editor. "
                   "Please specify $EDITOR or use ~/.bzr.conf/editor")
                          

def edit_commit_message(infotext, ignoreline=None):
    """Let the user edit a commit message in a temp file.

    This is run if they don't give a message or
    message-containing file on the command line.

    infotext:
        Text to be displayed at bottom of message for
        the user's reference; currently similar to
        'bzr status'.
    """
    import tempfile
    
    if ignoreline is None:
        ignoreline = "-- This line and the following will be ignored --"
        
    try:
        tmp_fileno, msgfilename = tempfile.mkstemp(prefix='bzr_log.', dir=u'.')
        msgfile = os.close(tmp_fileno)
        if infotext is not None and infotext != "":
            hasinfo = True
            msgfile = file(msgfilename, "w")
            msgfile.write("\n\n%s\n\n%s" % (ignoreline, infotext))
            msgfile.close()
        else:
            hasinfo = False

        if not _run_editor(msgfilename):
            return None
        
        started = False
        msg = []
        lastline, nlines = 0, 0
        for line in file(msgfilename, "r"):
            stripped_line = line.strip()
            # strip empty line before the log message starts
            if not started:
                if stripped_line != "":
                    started = True
                else:
                    continue
            # check for the ignore line only if there
            # is additional information at the end
            if hasinfo and stripped_line == ignoreline:
                break
            nlines += 1
            # keep track of the last line that had some content
            if stripped_line != "":
                lastline = nlines
            msg.append(line)
            
        if len(msg) == 0:
            return ""
        # delete empty lines at the end
        del msg[lastline:]
        # add a newline at the end, if needed
        if not msg[-1].endswith("\n"):
            return "%s%s" % ("".join(msg), "\n")
        else:
            return "".join(msg)
    finally:
        # delete the msg file in any case
        try: os.unlink(msgfilename)
        except IOError: pass

