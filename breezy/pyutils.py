# Copyright (C) 2010 Canonical Ltd
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

"""General Python convenience functions."""

import sys


def get_named_object(module_name, member_name=None):
    """Get the Python object named by a given module and member name.

    This is usually much more convenient than dealing with ``__import__``
    directly::

        >>> doc = get_named_object('breezy.pyutils', 'get_named_object.__doc__')
        >>> doc.splitlines()[0]
        'Get the Python object named by a given module and member name.'

    :param module_name: a module name, as would be found in sys.modules if
        the module is already imported.  It may contain dots.  e.g. 'sys' or
        'os.path'.
    :param member_name: (optional) a name of an attribute in that module to
        return.  It may contain dots.  e.g. 'MyClass.some_method'.  If not
        given, the named module will be returned instead.
    :raises: ImportError or AttributeError.
    """
    # We may have just a module name, or a module name and a member name,
    # and either may contain dots.  __import__'s return value is a bit
    # unintuitive, so we need to take care to always return the object
    # specified by the full combination of module name + member name.
    if member_name:
        # Give __import__ a from_list.  It will return the last module in
        # the dotted module name.
        attr_chain = member_name.split('.')
        from_list = attr_chain[:1]
        obj = __import__(module_name, {}, {}, from_list)
        for attr in attr_chain:
            obj = getattr(obj, attr)
    else:
        # We're just importing a module, no attributes, so we have no
        # from_list.  __import__ will return the first module in the dotted
        # module name, so we look up the module from sys.modules.
        __import__(module_name, globals(), locals(), [])
        obj = sys.modules[module_name]
    return obj


def calc_parent_name(module_name, member_name=None):
    """Determine the 'parent' of a given dotted module name and (optional)
    member name.

    The idea is that ``getattr(parent_obj, final_attr)`` will equal
    get_named_object(module_name, member_name).

    :return: (module_name, member_name, final_attr) tuple.
    """
# +SKIP is not recognized by python2.4
# Typical use is::
#
#     >>> parent_mod, parent_member, final_attr = calc_parent_name(
#     ...     module_name, member_name) # doctest: +SKIP
#     >>> parent_obj = get_named_object(parent_mod, parent_member)
#     ... # doctest: +SKIP
    if member_name is not None:
        split_name = member_name.rsplit('.', 1)
        if len(split_name) == 1:
            return (module_name, None, member_name)
        else:
            return (module_name, split_name[0], split_name[1])
    else:
        split_name = module_name.rsplit('.', 1)
        if len(split_name) == 1:
            raise AssertionError(
                'No parent object for top-level module %r' % (module_name,))
        else:
            return (split_name[0], None, split_name[1])
