# Copyright (c) 2004 Canonical Limited
#       Author: Robert Collins <robert.collins@canonical.com>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

import sys
import logging
import unittest


class LogCollector(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.records=[]
    def emit(self, record):
        self.records.append(record.getMessage())


def makeCollectingLogger():
    """I make a logger instance that collects its logs for programmatic analysis
    -> (logger, collector)"""
    logger=logging.Logger("collector")
    handler=LogCollector()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    return logger, handler


def visitTests(suite, visitor):
    """A foreign method for visiting the tests in a test suite."""
    for test in suite._tests:
        #Abusing types to avoid monkey patching unittest.TestCase. 
        # Maybe that would be better?
        try:
            test.visit(visitor)
        except AttributeError:
            if isinstance(test, unittest.TestCase):
                visitor.visitCase(test)
            elif isinstance(test, unittest.TestSuite):
                visitor.visitSuite(test)
                visitTests(test, visitor)
            else:
                print "unvisitable non-unittest.TestCase element %r (%r)" % (test, test.__class__)
    

class TestSuite(unittest.TestSuite):
    """I am an extended TestSuite with a visitor interface.
    This is primarily to allow filtering of tests - and suites or
    more in the future. An iterator of just tests wouldn't scale..."""

    def visit(self, visitor):
        """visit the composite. Visiting is depth-first.
        current callbacks are visitSuite and visitCase."""
        visitor.visitSuite(self)
        visitTests(self, visitor)


class TestLoader(unittest.TestLoader):
    """Custom  TestLoader to address some quirks in the stock python one."""
    suiteClass = TestSuite

    def loadTestsFromModuleNames(self, names):
        """use a custom means to load tests from modules.

        There is an undesirable glitch in the python TestLoader where a 
        import error is ignore. We think this can be solved by ensuring the 
        requested name is resolvable, if its not raising the original error.
        """
        result = self.suiteClass()
        for name in names:
            _load_module_by_name(name)
            result.addTests(self.loadTestsFromName(name))
        return result


def _load_module_by_name(mod_name):
    parts = mod_name.split('.')
    module = __import__(mod_name)
    del parts[0]
    # for historical reasons python returns the top-level module even though
    # it loads the submodule; we need to walk down to get the one we want.
    while parts:
        module = getattr(module, parts.pop(0))
    return module


class TestVisitor(object):
    """A visitor for Tests"""
    def visitSuite(self, aTestSuite):
        pass
    def visitCase(self, aTestCase):
        pass
