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

"""Classes to provide name-to-object registry-like support."""

from collections.abc import Callable
from typing import (
    TypeVar,
    Union,
)

from catalogus import Registry
from catalogus.registry import _LazyObjectGetter, _ObjectGetter

__all__ = ["Registry", "FormatRegistry", "_LazyObjectGetter", "_ObjectGetter"]

Format = TypeVar("Format")


class FormatRegistry(Registry[str, Union[Format, Callable[[], Format]], None]):
    """Registry specialised for handling formats."""

    def __init__(self, other_registry=None):
        super().__init__()
        self._other_registry = other_registry

    def register(self, key, obj, help=None, info=None, override_existing=False):
        Registry.register(
            self, key, obj, help=help, info=info, override_existing=override_existing
        )
        if self._other_registry is not None:
            self._other_registry.register(
                key, obj, help=help, info=info, override_existing=override_existing
            )

    def register_lazy(
        self,
        key,
        module_name,
        member_name,
        help=None,
        info=None,
        override_existing=False,
    ):
        # Overridden to allow capturing registrations to two seperate
        # registries in a single call.
        Registry.register_lazy(
            self,
            key,
            module_name,
            member_name,
            help=help,
            info=info,
            override_existing=override_existing,
        )
        if self._other_registry is not None:
            self._other_registry.register_lazy(
                key,
                module_name,
                member_name,
                help=help,
                info=info,
                override_existing=override_existing,
            )

    def remove(self, key):
        super().remove(key)
        if self._other_registry is not None:
            self._other_registry.remove(key)

    def get(self, format_string):
        r = Registry.get(self, format_string)
        if callable(r):
            r = r()
        return r
