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

from typing import (
    TypeVar,
)

from ._cmd_rs.registry import Registry, _LazyObjectGetter, _ObjectGetter

__all__ = ["FormatRegistry", "Registry", "_LazyObjectGetter", "_ObjectGetter"]

Format = TypeVar("Format")
Info = TypeVar("Info")


# FormatRegistry mirrors registrations into an optional second registry and
# calls a registered factory on get, so callers see the format rather than the
# callable.
from ._cmd_rs.registry import FormatRegistry
