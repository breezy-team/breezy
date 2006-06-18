# Copyright (C) 2006 by Canonical Ltd
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

"""A custom importer and regex compiler which logs time."""

import os
import sys
import time
import sre


_import_logfile = sys.stderr
_compile_logfile = sys.stderr

_real_import = __import__

def _custom_import(name, globals, locals, fromlist):
    """Wrap around standard importer to log import time"""
    if _import_logfile is None:
        return _real_import(name, globals, locals, fromlist)

    scope_name = globals.get('__name__', None)
    if scope_name is None:
        scope_name = globals.get('__file__', None)
    if scope_name is None:
        scope_name = globals.keys()
    else:
        # Trim out paths before bzrlib
        loc = scope_name.find('bzrlib')
        if loc != -1:
            scope_name = scope_name[loc:]
        # For stdlib, trim out early paths
        loc = scope_name.find('python2.4')
        if loc != -1:
            scope_name = scope_name[loc:]
                
    # Do the import
    tstart = time.time()
    mod = _real_import(name, globals, locals, fromlist)
    tload = time.time()-tstart

    # Figure out the frame that is doing the importing
    frame = sys._getframe(1)
    frame_name = frame.f_globals.get('__name__', '<unknown>')
    extra = ''
    cur_frame = 1
    if frame_name.endswith('demandload'):
        # If this was demandloaded, we have 3 frames to ignore
        extra = ' (demandload)'
        frame = sys._getframe(4)
        cur_frame = 4
        frame_name = frame.f_globals.get('__name__', '<unknown>')
    frame_lineno = frame.f_lineno

    # Log the import
    _import_logfile.write('%3.0fms %-24s\tfor %-24s\t@ %s:%d%s\n' 
        % ((time.time()-tstart)*1000, name, scope_name,
            frame_name, frame_lineno, extra))

    # If the import took a long time, log the stack that generated
    # this import. Especially necessary for demandloaded code
    if tload > 0.01:
        stack = []
        for fnum in range(cur_frame+1, cur_frame+10):
            try:
                f = sys._getframe(fnum)
            except ValueError:
                break
            stack.append('%s:%i' 
                    % (f.f_globals.get('__name__', '<unknown>'),
                        f.f_lineno)
                    )
        if stack:
            _import_logfile.write('\t' + ' '.join(stack) + '\n')
    return mod


_real_compile = sre._compile

def _custom_compile(*args, **kwargs):
    """Log how long it takes to compile a regex"""
    if _compile_logfile is None:
        return _real_compile(*args, **kwargs)

    # Measure the compile time
    tstart = time.time()
    comp = _real_compile(*args, **kwargs)
    
    # And who is requesting this?
    frame = sys._getframe(2)
    frame_name = frame.f_globals.get('__name__', '<unknown>')
    frame_lineno = frame.f_lineno
    _compile_logfile.write('%3.0fms %-40r\t@ %s:%d\n'
        % ((time.time()-tstart)*1000, args[0][:40], 
            frame_name, frame_lineno))
    return comp

__builtins__.__import__ = _custom_import
sre._compile = _custom_compile
