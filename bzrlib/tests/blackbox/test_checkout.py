# Copyright (C) 2005 by Canonical Ltd
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the 'checkout' CLI command."""

from cStringIO import StringIO
import os
import re
import shutil
import sys

import bzrlib.bzrdir as bzrdir
from bzrlib.tests.blackbox import ExternalBase


class TestCheckout(ExternalBase):
    
    def setUp(self):
        super(TestCheckout, self).setUp()
        bzrdir.BzrDir.create_standalone_workingtree('branch')

    def test_checkout_makes_checkout(self):
        self.runbzr('checkout branch checkout')
        # if we have a checkout, the branch base should be 'branch'
        source = bzrdir.BzrDir.open('branch')
        result = bzrdir.BzrDir.open('checkout')
        self.assertEqual(source.open_branch().bzrdir.root_transport.base,
                         result.open_branch().bzrdir.root_transport.base)
