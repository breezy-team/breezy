# Copyright (C) 2005 Canonical Ltd
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


import inspect


__all__ = ['needs_read_lock',
           'needs_write_lock',
           ]


def _get_parameters(func):
    """Recreate the parameters for a function using introspection.

    :return: (function_params, passed_params)
        function_params is the list of parameters to the original function.
        This is something like "a, b, c=None, d=1"
        passed_params is how you would pass the parameters to a new function.
        This is something like "a=a, b=b, c=c, d=d"
    """
    args, varargs, varkw, defaults = inspect.getargspec(func)
    formatted = inspect.formatargspec(args, varargs=varargs,
                                      varkw=varkw,
                                      defaults=defaults)
    if defaults is None:
        args_passed = args
    else:
        first_default = len(args) - len(defaults)
        args_passed = args[:first_default]
        for arg in args[first_default:]:
            args_passed.append("%s=%s" % (arg, arg))
    if varargs is not None:
        args_passed.append('*' + varargs)
    if varkw is not None:
        args_passed.append('**' + varkw)
    args_passed = ', '.join(args_passed)

    return formatted[1:-1], args_passed


def needs_read_lock(unbound):
    """Decorate unbound to take out and release a read lock.

    This decorator can be applied to methods of any class with lock_read() and
    unlock() methods.
    
    Typical usage:
        
    class Branch(...):
        @needs_read_lock
        def branch_method(self, ...):
            stuff
    """
    # This compiles a function with a similar name, but wrapped with
    # lock_read/unlock calls. We use dynamic creation, because we need the
    # internal name of the function to be modified so that --lsprof will see
    # the correct name.
    # TODO: jam 20070111 Modify this template so that the generated function
    #       has the same argument signature as the original function, which
    #       will help commands like epydoc.
    #       This seems possible by introspecting foo.func_defaults, and
    #       foo.func_code.co_argcount and foo.func_code.co_varnames
    template = """\
def %(name)s_read_locked(%(params)s):
    self.lock_read()
    try:
        return unbound(%(passed_params)s)
    finally:
        self.unlock()
read_locked = %(name)s_read_locked
"""
    params, passed_params = _get_parameters(unbound)
    variables = {'name':unbound.__name__,
                 'params':params,
                 'passed_params':passed_params,
                }
    func_def = template % variables

    exec func_def in locals()

    read_locked.__doc__ = unbound.__doc__
    read_locked.__name__ = unbound.__name__
    return read_locked


def needs_write_lock(unbound):
    """Decorate unbound to take out and release a write lock."""
    template = """\
def %(name)s_write_locked(%(params)s):
    self.lock_write()
    try:
        return unbound(%(passed_params)s)
    finally:
        self.unlock()
write_locked = %(name)s_write_locked
"""
    params, passed_params = _get_parameters(unbound)
    variables = {'name':unbound.__name__,
                 'params':params,
                 'passed_params':passed_params,
                }
    func_def = template % variables

    exec func_def in locals()

    write_locked.__doc__ = unbound.__doc__
    write_locked.__name__ = unbound.__name__
    return write_locked

