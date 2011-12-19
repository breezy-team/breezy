# Copyright (C) 2006-2010 Canonical Ltd
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

from __future__ import absolute_import

__all__ = ['needs_read_lock',
           'needs_write_lock',
           'use_fast_decorators',
           'use_pretty_decorators',
           ]


import sys

from bzrlib import trace


def _get_parameters(func):
    """Recreate the parameters for a function using introspection.

    :return: (function_params, calling_params, default_values)
        function_params: is a string representing the parameters of the
            function. (such as "a, b, c=None, d=1")
            This is used in the function declaration.
        calling_params: is another string representing how you would call the
            function with the correct parameters. (such as "a, b, c=c, d=d")
            Assuming you used function_params in the function declaration, this
            is the parameters to put in the function call.
        default_values_block: a dict with the default values to be passed as
            the scope for the 'exec' statement.

        For example:

        def wrapper(%(function_params)s):
            return original(%(calling_params)s)
    """
    # "import inspect" should stay in local scope. 'inspect' takes a long time
    # to import the first time. And since we don't always need it, don't import
    # it globally.
    import inspect
    args, varargs, varkw, defaults = inspect.getargspec(func)
    defaults_dict = {}
    def formatvalue(value):
        default_name = '__default_%d' % len(defaults_dict)
        defaults_dict[default_name] = value
        return '=' + default_name
    formatted = inspect.formatargspec(args, varargs=varargs,
                                      varkw=varkw,
                                      defaults=defaults,
                                      formatvalue=formatvalue)
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

    return formatted[1:-1], args_passed, defaults_dict


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
        result = unbound(%(passed_params)s)
    except:
        import sys
        exc_info = sys.exc_info()
        try:
            self.unlock()
        finally:
            try:
                raise exc_info[0], exc_info[1], exc_info[2]
            finally:
                del exc_info
    else:
        self.unlock()
        return result
read_locked = %(name)s_read_locked
"""
    params, passed_params, defaults_dict = _get_parameters(unbound)
    variables = {'name':unbound.__name__,
                 'params':params,
                 'passed_params':passed_params,
                }
    func_def = template % variables

    scope = dict(defaults_dict)
    scope['unbound'] = unbound
    exec func_def in scope
    read_locked = scope['read_locked']

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
            result = unbound(self, *args, **kwargs)
        except:
            import sys
            exc_info = sys.exc_info()
            try:
                self.unlock()
            finally:
                try:
                    raise exc_info[0], exc_info[1], exc_info[2]
                finally:
                    del exc_info
        else:
            self.unlock()
            return result
    read_locked.__doc__ = unbound.__doc__
    read_locked.__name__ = unbound.__name__
    return read_locked


def _pretty_needs_write_lock(unbound):
    """Decorate unbound to take out and release a write lock."""
    template = """\
def %(name)s_write_locked(%(params)s):
    self.lock_write()
    try:
        result = unbound(%(passed_params)s)
    except:
        import sys
        exc_info = sys.exc_info()
        try:
            self.unlock()
        finally:
            try:
                raise exc_info[0], exc_info[1], exc_info[2]
            finally:
                del exc_info
    else:
        self.unlock()
        return result
write_locked = %(name)s_write_locked
"""
    params, passed_params, defaults_dict = _get_parameters(unbound)
    variables = {'name':unbound.__name__,
                 'params':params,
                 'passed_params':passed_params,
                }
    func_def = template % variables

    scope = dict(defaults_dict)
    scope['unbound'] = unbound
    exec func_def in scope
    write_locked = scope['write_locked']

    write_locked.__doc__ = unbound.__doc__
    write_locked.__name__ = unbound.__name__
    return write_locked


def _fast_needs_write_lock(unbound):
    """Decorate unbound to take out and release a write lock."""
    def write_locked(self, *args, **kwargs):
        self.lock_write()
        try:
            result = unbound(self, *args, **kwargs)
        except:
            exc_info = sys.exc_info()
            try:
                self.unlock()
            finally:
                try:
                    raise exc_info[0], exc_info[1], exc_info[2]
                finally:
                    del exc_info
        else:
            self.unlock()
            return result
    write_locked.__doc__ = unbound.__doc__
    write_locked.__name__ = unbound.__name__
    return write_locked


def only_raises(*errors):
    """Make a decorator that will only allow the given error classes to be
    raised.  All other errors will be logged and then discarded.

    Typical use is something like::

        @only_raises(LockNotHeld, LockBroken)
        def unlock(self):
            # etc
    """
    def decorator(unbound):
        def wrapped(*args, **kwargs):
            try:
                return unbound(*args, **kwargs)
            except errors:
                raise
            except:
                trace.mutter('Error suppressed by only_raises:')
                trace.log_exception_quietly()
        wrapped.__doc__ = unbound.__doc__
        wrapped.__name__ = unbound.__name__
        return wrapped
    return decorator


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


# This implementation of cachedproperty is copied from Launchpad's
# canonical.launchpad.cachedproperty module (with permission from flacoste)
# -- spiv & vila 100120
def cachedproperty(attrname_or_fn):
    """A decorator for methods that makes them properties with their return
    value cached.

    The value is cached on the instance, using the attribute name provided.

    If you don't provide a name, the mangled name of the property is used.

    >>> class CachedPropertyTest(object):
    ...
    ...     @cachedproperty('_foo_cache')
    ...     def foo(self):
    ...         print 'foo computed'
    ...         return 23
    ...
    ...     @cachedproperty
    ...     def bar(self):
    ...         print 'bar computed'
    ...         return 69

    >>> cpt = CachedPropertyTest()
    >>> getattr(cpt, '_foo_cache', None) is None
    True
    >>> cpt.foo
    foo computed
    23
    >>> cpt.foo
    23
    >>> cpt._foo_cache
    23
    >>> cpt.bar
    bar computed
    69
    >>> cpt._bar_cached_value
    69

    """
    if isinstance(attrname_or_fn, basestring):
        attrname = attrname_or_fn
        return _CachedPropertyForAttr(attrname)
    else:
        fn = attrname_or_fn
        attrname = '_%s_cached_value' % fn.__name__
        return _CachedProperty(attrname, fn)


class _CachedPropertyForAttr(object):

    def __init__(self, attrname):
        self.attrname = attrname

    def __call__(self, fn):
        return _CachedProperty(self.attrname, fn)


class _CachedProperty(object):

    def __init__(self, attrname, fn):
        self.fn = fn
        self.attrname = attrname
        self.marker = object()

    def __get__(self, inst, cls=None):
        if inst is None:
            return self
        cachedresult = getattr(inst, self.attrname, self.marker)
        if cachedresult is self.marker:
            result = self.fn(inst)
            setattr(inst, self.attrname, result)
            return result
        else:
            return cachedresult
