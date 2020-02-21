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

from . import trace


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
    ...         print('foo computed')
    ...         return 23
    ...
    ...     @cachedproperty
    ...     def bar(self):
    ...         print('bar computed')
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
    if isinstance(attrname_or_fn, str):
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
