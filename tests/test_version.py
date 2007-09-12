#    test_version.py -- Testsuite for builddeb version
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#    
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from bzrlib.plugins import builddeb

import bzrlib
from bzrlib.tests import TestCase, KnownFailure
from bzrlib.trace import error

class VersionTests(TestCase):

  def test_version_matches(self):
    """An abused test case to warn when the version doesn't match bzrlib."""
    if builddeb.version_info != bzrlib.version_info:
      raise KnownFailure("builddeb version doesn't match bzrlib version")

