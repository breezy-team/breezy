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


__all__ = ['needs_read_lock',
           'needs_write_lock',
           'use_fast_decorators',
           'use_pretty_decorators',
           ]


def _get_parameters(func):
    """Recreate the parameters for a function using introspection.

    :return: (function_params, calling_params)
        function_params: is a string representing the parameters of the
            function. (such as "a, b, c=None, d=1")
            This is used in the function declaration.
        calling_params: is another string representing how you would call the
            function with the correct parameters. (such as "a, b, c=c, d=d")
            Assuming you sued function_params in the function declaration, this
            is the parameters to put in the function call.

        For example:

        def wrapper(%(function_params)s):
            return original(%(calling_params)s)
    """
    # "import inspect" should stay in local scope. 'inspect' takes a long time
    # to import the first time. And since we don't always need it, don't import
    # it globally.
    import inspect
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


def _pretty_needs_read_lock(unbound):
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


def _fast_needs_read_lock(unbound):
    """Decorate unbound to take out and release a read lock.

    This decorator can be applied to methods of any class with lock_read() and
    unlock() methods.
    
    Typical usage:
        
    class Branch(...):
        @needs_read_lock
        def branch_method(self, ...):
            stuff
    """
    def read_locked(self, *args, **kwargs):
        self.lock_read()
        try:
            return unbound(self, *args, **kwargs)
        finally:
            self.unlock()
    read_locked.__doc__ = unbound.__doc__
    read_locked.__name__ = unbound.__name__
    return read_locked


def _pretty_needs_write_lock(unbound):
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


def _fast_needs_write_lock(unbound):
    """Decorate unbound to take out and release a write lock."""
    def write_locked(self, *args, **kwargs):
        self.lock_write()
        try:
            return unbound(self, *args, **kwargs)
        finally:
            self.unlock()
    write_locked.__doc__ = unbound.__doc__
    write_locked.__name__ = unbound.__name__
    return write_locked


# Default is more functionality, 'bzr' the commandline will request fast
# versions.
needs_read_lock = _pretty_needs_read_lock
needs_write_lock = _pretty_needs_write_lock


def use_fast_decorators():
    """Change the default decorators to be fast loading ones.

    The alternative is to have decorators that do more work to produce
    nice-looking decorated functions, but this slows startup time.
    """
    global needs_read_lock, needs_write_lock
    needs_read_lock = _fast_needs_read_lock
    needs_write_lock = _fast_needs_write_lock


def use_pretty_decorators():
    """Change the default decorators to be pretty ones."""
    global needs_read_lock, needs_write_lock
    needs_read_lock = _pretty_needs_read_lock
    needs_write_lock = _pretty_needs_write_lock
