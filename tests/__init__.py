#    __init__.py -- Testsuite for builddeb
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

import doctest
from unittest import TestSuite

from bzrlib.tests import TestUtil

import changes
import config

def test_suite():
    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = [
            'test_builder',
            'test_util',
            ]
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i)
                                            for i in testmod_names]))

    doctest_mod_names = [
             'changes',
             'config'
             ]
    for mod in doctest_mod_names:
      suite.addTest(doctest.DocTestSuite(mod))

    return suite

