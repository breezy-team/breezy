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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""Tests for the revision/inventory Serializers."""


from .. import (
    chk_serializer,
    serializer,
    xml5,
    xml6,
    xml7,
    xml8,
    )
from . import TestCase


class TestSerializer(TestCase):
    """Test serializer"""

    def test_registry(self):
        self.assertIs(xml5.serializer_v5,
                      serializer.format_registry.get('5'))
        self.assertIs(xml6.serializer_v6,
                      serializer.format_registry.get('6'))
        self.assertIs(xml7.serializer_v7,
                      serializer.format_registry.get('7'))
        self.assertIs(xml8.serializer_v8,
                      serializer.format_registry.get('8'))
        self.assertIs(chk_serializer.chk_serializer_255_bigpage,
                      serializer.format_registry.get('9'))
