# Copyright (C) 2006, 2007, 2009 Canonical Ltd
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

import os
from StringIO import StringIO

from bzrlib import errors
from bzrlib.progress import (
        DummyProgress,
        ChildProgress,
        TTYProgressBar,
        DotsProgressBar,
        )
from bzrlib.tests import TestCase
from bzrlib.symbol_versioning import (
    deprecated_in,
    )


class _TTYStringIO(StringIO):
    """A helper class which makes a StringIO look like a terminal"""

    def isatty(self):
        return True


class _NonTTYStringIO(StringIO):
    """Helper that implements isatty() but returns False"""

    def isatty(self):
        return False
