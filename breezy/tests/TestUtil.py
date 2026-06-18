# Copyright (C) 2005-2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#

import logging
import unittest
import weakref

from catalogus import pyutils

# Mark this python module as being part of the implementation
# of unittest: this gives us better tracebacks where the last
# shown frame is the test code, not our assertXYZ.
__unittest = 1


class LogCollector(logging.Handler):
    def __init__(self) -> None:
        logging.Handler.__init__(self)
        self.records: list[str] = []

    def emit(self, record) -> None:
        self.records.append(record.getMessage())


def makeCollectingLogger():
    """I make a logger instance that collects its logs for programmatic analysis
    -> (logger, collector).
    """
    logger = logging.Logger("collector")
    handler = LogCollector()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    return logger, handler


def visitTests(suite, visitor):
    """A foreign method for visiting the tests in a test suite."""
    for test in suite._tests:
        # Abusing types to avoid monkey patching unittest.TestCase.
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
                print(
                    "unvisitable non-unittest.TestCase element {!r} ({!r})".format(
                        test, test.__class__
                    )
                )


class FailedCollectionCase(unittest.TestCase):
    """Pseudo-test to run and report failure if given case was uncollected."""

    def __init__(self, case):
        super().__init__("fail_uncollected")
        # GZ 2011-09-16: Maybe catch errors from id() method as cases may be
        #                in a bit of a funny state by now.
        self._problem_case_id = case.id()

    def id(self):
        if self._problem_case_id[-1:] == ")":
            return self._problem_case_id[:-1] + ",uncollected)"
        return self._problem_case_id + "(uncollected)"

    def fail_uncollected(self):
        self.fail("Uncollected test case: " + self._problem_case_id)


class TestSuite(unittest.TestSuite):
    """I am an extended TestSuite with a visitor interface.
    This is primarily to allow filtering of tests - and suites or
    more in the future. An iterator of just tests wouldn't scale...
    """

    def visit(self, visitor):
        """Visit the composite. Visiting is depth-first.
        current callbacks are visitSuite and visitCase.
        """
        visitor.visitSuite(self)
        visitTests(self, visitor)

    def run(self, result):
        """Run the tests in the suite, discarding references after running."""
        tests = list(self)
        tests.reverse()
        self._tests = []
        stored_count = 0
        count_stored_tests = getattr(result, "_count_stored_tests", int)
        from breezy.tests import selftest_debug_flags

        notify = "uncollected_cases" in selftest_debug_flags
        while tests:
            if result.shouldStop:
                self._tests = reversed(tests)
                break
            case = _run_and_collect_case(tests.pop(), result)()
            new_stored_count = count_stored_tests()
            if case is not None and isinstance(case, unittest.TestCase):
                if stored_count == new_stored_count and notify:
                    # Testcase didn't fail, but somehow is still alive
                    FailedCollectionCase(case).run(result)
                    # Adding a new failure so need to reupdate the count
                    new_stored_count = count_stored_tests()
                # GZ 2011-09-16: Previously zombied the case at this point by
                #                clearing the dict as fallback, skip for now.
            stored_count = new_stored_count
        return result


def _run_and_collect_case(case, res):
    """Run test case against result and use weakref to drop the refcount."""
    case.run(res)
    return weakref.ref(case)


class TestLoader(unittest.TestLoader):
    """Custom TestLoader to extend the stock python one."""

    suiteClass = TestSuite  # noqa: N815
    # Memoize test names by test class dict
    test_func_names: dict[str, list[str]] = {}

    def loadTestsFromModuleNames(self, names):
        """Use a custom means to load tests from modules.

        There is an undesirable glitch in the python TestLoader where a
        import error is ignore. We think this can be solved by ensuring the
        requested name is resolvable, if its not raising the original error.
        """
        result = self.suiteClass()
        for name in names:
            result.addTests(self.loadTestsFromModuleName(name))
        return result

    def loadTestsFromModuleName(self, name):
        result = self.suiteClass()
        module = pyutils.get_named_object(name)

        result.addTests(self.loadTestsFromModule(module))
        return result

    def getTestCaseNames(self, test_case_class):
        test_fn_names = self.test_func_names.get(test_case_class, None)
        if test_fn_names is not None:
            # We already know them
            return test_fn_names

        test_fn_names = unittest.TestLoader.getTestCaseNames(self, test_case_class)
        self.test_func_names[test_case_class] = test_fn_names
        return test_fn_names


class FilteredByModuleTestLoader(TestLoader):
    """A test loader that import only the needed modules."""

    def __init__(self, needs_module):
        """Constructor.

        :param needs_module: a callable taking a module name as a
            parameter returing True if the module should be loaded.
        """
        TestLoader.__init__(self)
        self.needs_module = needs_module

    def loadTestsFromModuleName(self, name):
        if self.needs_module(name):
            return TestLoader.loadTestsFromModuleName(self, name)
        else:
            return self.suiteClass()


class TestVisitor:
    """A visitor for Tests."""

    def visitSuite(self, a_test_suite):
        pass

    def visitCase(self, a_test_case):
        pass
