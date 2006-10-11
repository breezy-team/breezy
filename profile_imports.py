# Copyright (C) 2006 by Canonical Ltd
# Written by John Arbash Meinel <john@arbash-meinel.com>
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

"""A custom importer and regex compiler which logs time spent."""

import sre
import sys
import time


_parent_stack = []
_total_stack = {}
_info = {}
_cur_id = 0


def stack_add(name, frame_name, frame_lineno, scope_name=None):
    """Start a new record on the stack"""
    global _cur_id
    _cur_id += 1
    this_stack = (_cur_id, name)

    if _parent_stack:
        _total_stack[_parent_stack[-1]].append(this_stack)
    _total_stack[this_stack] = []
    _parent_stack.append(this_stack)
    _info[this_stack] = [len(_parent_stack)-1, frame_name, frame_lineno, scope_name]

    return this_stack


def stack_finish(this, cost):
    """Finish a given entry, and record its cost in time"""
    global _parent_stack

    assert _parent_stack[-1] == this, \
        'import stack does not end with this %s: %s' % (this, _parent_stack)
    _parent_stack.pop()
    _info[this].append(cost)


def log_stack_info(out_file, sorted=True, hide_fast=True):
    # Find all of the roots with import = 0
    out_file.write(' cum  inline name\t\t\t\t\t\tframe\n')
    todo = [(value[-1], key) for key,value in _info.iteritems() if value[0] == 0]

    if sorted:
        todo.sort()

    while todo:
        cum_time, cur = todo.pop()
        children = _total_stack[cur]

        c_times = []

        info = _info[cur]
        if hide_fast and info[-1] < 0.0001:
            continue

        # Compute the module time by removing the children times
        mod_time = info[-1]
        for child in children:
            c_info = _info[child]
            mod_time -= c_info[-1]
            c_times.append((c_info[-1], child))

        # indent, cum_time, mod_time, name,
        # scope_name, frame_name, frame_lineno
        out_file.write('%5.1f %5.1f %s %-35s\t@ %s:%d\n'
            % (info[-1]*1000., mod_time*1000., '+'*info[0], 
               cur[1][:35], info[1], info[2]))

        if sorted:
            c_times.sort()
        else:
            c_times.reverse()
        todo.extend(c_times)


_real_import = __import__

def timed_import(name, globals, locals, fromlist):
    """Wrap around standard importer to log import time"""

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

    # Figure out the frame that is doing the importing
    frame = sys._getframe(1)
    frame_name = frame.f_globals.get('__name__', '<unknown>')
    extra = ''
    if frame_name.endswith('demandload'):
        # If this was demandloaded, we have 3 frames to ignore
        extra = '(demandload) '
        frame = sys._getframe(4)
        frame_name = frame.f_globals.get('__name__', '<unknown>')
    elif frame_name.endswith('lazy_import'):
        # If this was lazily imported, we have 3 frames to ignore
        extra = '[l] '
        frame = sys._getframe(4)
        frame_name = frame.f_globals.get('__name__', '<unknown>')
    if fromlist:
        extra += ' [%s]' % (', '.join(map(str, fromlist)),)
    frame_lineno = frame.f_lineno

    this = stack_add(extra + name, frame_name, frame_lineno, scope_name)

    tstart = time.time()
    try:
        # Do the import
        mod = _real_import(name, globals, locals, fromlist)
    finally:
        tload = time.time()-tstart
        stack_finish(this, tload)

    return mod


_real_compile = sre._compile

def timed_compile(*args, **kwargs):
    """Log how long it takes to compile a regex"""

    # And who is requesting this?
    frame = sys._getframe(2)
    frame_name = frame.f_globals.get('__name__', '<unknown>')

    extra = ''
    if frame_name.endswith('lazy_regex'):
        # If this was lazily compiled, we have 3 more frames to ignore
        extra = '[l] '
        frame = sys._getframe(5)
        frame_name = frame.f_globals.get('__name__', '<unknown>')
    frame_lineno = frame.f_lineno
    this = stack_add(extra+repr(args[0]), frame_name, frame_lineno)

    tstart = time.time()
    try:
        # Measure the compile time
        comp = _real_compile(*args, **kwargs)
    finally:
        tcompile = time.time() - tstart
        stack_finish(this, tcompile)

    return comp


def install():
    """Install the hooks for measuring import and regex compile time."""
    __builtins__['__import__'] = timed_import
    sre._compile = timed_compile


def uninstall():
    """Remove the import and regex compile timing hooks."""
    __builtins__['__import__'] = _real_import
    sre._compile = _real_compile

