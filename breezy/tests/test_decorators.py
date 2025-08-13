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


"""Tests for decorator functions."""

from .. import decorators
from . import TestCase


class SampleUnlockError(Exception):
    """Sample exception for testing purposes."""

    pass


class TestOnlyRaisesDecorator(TestCase):
    """Tests for the only_raises decorator functionality."""

    def raise_ZeroDivisionError(self):
        """Test helper method that raises ZeroDivisionError."""
        1 / 0  # noqa: B018

    def test_raises_approved_error(self):
        """Test that approved errors are raised normally."""
        decorator = decorators.only_raises(ZeroDivisionError)
        decorated_meth = decorator(self.raise_ZeroDivisionError)
        self.assertRaises(ZeroDivisionError, decorated_meth)

    def test_quietly_logs_unapproved_errors(self):
        """Test that unapproved errors are logged instead of raised."""
        decorator = decorators.only_raises(IOError)
        decorated_meth = decorator(self.raise_ZeroDivisionError)
        self.assertLogsError(ZeroDivisionError, decorated_meth)
