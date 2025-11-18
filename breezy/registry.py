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
)

from catalogus.registry import Registry

Format = TypeVar("Format")
Info = TypeVar("Info")


class FormatRegistry(Registry[str, Format | Callable[[], Format], Info]):
    """Registry specialised for handling formats."""

    def __init__(self, other_registry=None):
        """Initialize FormatRegistry.

        Args:
            other_registry: Optional additional registry to mirror registrations to.
        """
        super().__init__()
        self._other_registry = other_registry

    def register(self, key, obj, help=None, info=None, override_existing=False):
        """Register a format object.

        Args:
            key: The format name key.
            obj: The format object or factory function.
            help: Optional help text for this format.
            info: Optional additional information about the format.
            override_existing: Whether to allow overriding existing registrations.

        Returns:
            None
        """
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
        """Register a format that will be imported on first access.

        Args:
            key: The format name key.
            module_name: Name of the module containing the format.
            member_name: Name of the format object within the module.
            help: Optional help text for this format.
            info: Optional additional information about the format.
            override_existing: Whether to allow overriding existing registrations.

        Returns:
            None
        """
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
        """Remove a format from the registry.

        Args:
            key: The format name key to remove.

        Returns:
            None
        """
        super().remove(key)
        if self._other_registry is not None:
            self._other_registry.remove(key)

    def get(self, format_string):
        """Get a format object, calling factory functions if needed.

        Args:
            format_string: The format name to retrieve.

        Returns:
            The format object, with factory functions automatically called.
        """
        r = Registry.get(self, format_string)
        if callable(r):
            r = r()
        return r
