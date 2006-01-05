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

__all__ = ['warn', 'set_warning_method', 'zero_seven']

from warnings import warn


zero_seven = "%s was deprecated in version 0.7."


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
            warn(deprecation_version % symbol, DeprecationWarning)
            return callable(*args, **kwargs)
        _decorate_docstring(callable, deprecation_version, "function",
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
            warn(deprecation_version % symbol, DeprecationWarning)
            return callable(self, *args, **kwargs)
        _decorate_docstring(callable, deprecation_version, "method",
                            decorated_method)
        return decorated_method
    return method_decorator


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
