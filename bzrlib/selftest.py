# Copyright (C) 2005 by Canonical Ltd

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


from unittest import TestResult, TestCase

class _MyResult(TestResult):
#     def startTest(self, test):
#         print str(test).ljust(50),
#         TestResult.startTest(self, test)

#     def stopTest(self, test):
#         print
#         TestResult.stopTest(self, test)


    pass




def selftest():
     from unittest import TestLoader, TestSuite
     import bzrlib
     import bzrlib.whitebox
     import bzrlib.blackbox
     from doctest import DocTestSuite
    
     suite = TestSuite()
     tl = TestLoader()

     for m in bzrlib.whitebox, bzrlib.blackbox:
         suite.addTest(tl.loadTestsFromModule(m))

     for m in bzrlib.store, bzrlib.inventory, bzrlib.branch, bzrlib.osutils, \
             bzrlib.commands:
         suite.addTest(DocTestSuite(m))

     result = _MyResult()
     suite.run(result)

     print '%4d tests run' % result.testsRun
     print '%4d errors' % len(result.errors)
     print '%4d failures' % len(result.failures)

     return result.wasSuccessful()

