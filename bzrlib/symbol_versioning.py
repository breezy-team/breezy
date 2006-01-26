# Copyright (C) 2006 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Symbol versioning

The methods here allow for api symbol versioning.
"""

__all__ = ['deprecated_function',
           'deprecated_method',
           'DEPRECATED_PARAMETER',
           'deprecated_passed',
           'warn', 'set_warning_method', 'zero_seven',
           'zero_eight',
           ]

from warnings import warn


DEPRECATED_PARAMETER = "A deprecated parameter marker."
zero_seven = "%s was deprecated in version 0.7."
zero_eight = "%s was deprecated in version 0.8."


def set_warning_method(method):
    """Set the warning method to be used by this module.

    It should take a message and a warning category as warnings.warn does.
    """
    global warn
    warn = method


# TODO - maybe this would be easier to use as one 'smart' method that
# guess if it is a method or a class or an attribute ? If so, we can
# add that on top of the primitives, once we have all three written
# - RBC 20050105

def deprecated_function(deprecation_version):
    """Decorate a function so that use of it will trigger a warning."""

    def function_decorator(callable):
        """This is the function python calls to perform the decoration."""
        
        def decorated_function(*args, **kwargs):
            """This is the decorated function."""
            symbol = "%s.%s" % (callable.__module__, 
                                callable.__name__
                                )
            warn(deprecation_version % symbol, DeprecationWarning, stacklevel=2)
            return callable(*args, **kwargs)
        _populate_decorated(callable, deprecation_version, "function",
                            decorated_function)
        return decorated_function
    return function_decorator


def deprecated_method(deprecation_version):
    """Decorate a method so that use of it will trigger a warning.
    
    To deprecate an entire class, decorate __init__.
    """

    def method_decorator(callable):
        """This is the function python calls to perform the decoration."""
        
        def decorated_method(self, *args, **kwargs):
            """This is the decorated method."""
            symbol = "%s.%s.%s" % (self.__class__.__module__, 
                                   self.__class__.__name__,
                                   callable.__name__
                                   )
            warn(deprecation_version % symbol, DeprecationWarning, stacklevel=2)
            return callable(self, *args, **kwargs)
        _populate_decorated(callable, deprecation_version, "method",
                            decorated_method)
        return decorated_method
    return method_decorator


def deprecated_passed(parameter_value):
    """Return True if parameter_value was used."""
    # FIXME: it might be nice to have a parameter deprecation decorator. 
    # it would need to handle positional and *args and **kwargs parameters,
    # which means some mechanism to describe how the parameter was being
    # passed before deprecation, and some way to deprecate parameters that
    # were not at the end of the arg list. Thats needed for __init__ where
    # we cannot just forward to a new method name.I.e. in the following
    # examples we would want to have callers that pass any value to 'bad' be
    # given a warning - because we have applied:
    # @deprecated_parameter('bad', zero_seven)
    #
    # def __init__(self, bad=None)
    # def __init__(self, bad, other)
    # def __init__(self, **kwargs)
    # RBC 20060116
    return not parameter_value is DEPRECATED_PARAMETER


def _decorate_docstring(callable, deprecation_version, label,
                        decorated_callable):
    docstring_lines = callable.__doc__.split('\n')
    if len(docstring_lines) == 0:
        decorated_callable.__doc__ = deprecation_version % ("This " + label)
    elif len(docstring_lines) == 1:
        decorated_callable.__doc__ = (callable.__doc__ 
                                    + "\n"
                                    + "\n"
                                    + deprecation_version % ("This " + label)
                                    + "\n")
    else:
        spaces = len(docstring_lines[-1])
        new_doc = callable.__doc__
        new_doc += "\n" + " " * spaces
        new_doc += deprecation_version % ("This " + label)
        new_doc += "\n" + " " * spaces
        decorated_callable.__doc__ = new_doc


def _populate_decorated(callable, deprecation_version, label,
                        decorated_callable):
    """Populate attributes like __name__ and __doc__ on the decorated callable.
    """
    _decorate_docstring(callable, deprecation_version, label,
                        decorated_callable)
    decorated_callable.__module__ = callable.__module__
    decorated_callable.__name__ = callable.__name__
