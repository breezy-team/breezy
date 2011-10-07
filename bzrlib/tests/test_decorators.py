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


"""Tests for decorator functions"""

import inspect

from bzrlib import decorators
from bzrlib.tests import TestCase


class SampleUnlockError(Exception):
    pass


def create_decorator_sample(style, unlock_error=None, meth=None):
    """Create a DecoratorSample object, using specific lock operators.

    :param style: The type of lock decorators to use (fast/pretty/None)
    :param unlock_error: If specified, an error to raise from unlock.
    :param meth: a function to be decorated and added as a 'meth_read' and
        'meth_write' to the object.
    :return: An instantiated DecoratorSample object.
    """

    if style is None:
        # Default
        needs_read_lock = decorators.needs_read_lock
        needs_write_lock = decorators.needs_write_lock
    elif style == 'pretty':
        needs_read_lock = decorators._pretty_needs_read_lock
        needs_write_lock = decorators._pretty_needs_write_lock
    else:
        needs_read_lock = decorators._fast_needs_read_lock
        needs_write_lock = decorators._fast_needs_write_lock

    class DecoratorSample(object):
        """Sample class that uses decorators.

        Log when requests go through lock_read()/unlock() or
        lock_write()/unlock.
        """

        def __init__(self):
            self.actions = []

        def lock_read(self):
            self.actions.append('lock_read')

        def lock_write(self):
            self.actions.append('lock_write')

        @decorators.only_raises(SampleUnlockError)
        def unlock(self):
            if unlock_error:
                self.actions.append('unlock_fail')
                raise unlock_error
            else:
                self.actions.append('unlock')

        @needs_read_lock
        def frob(self):
            """Frob the sample object"""
            self.actions.append('frob')
            return 'newbie'

        @needs_write_lock
        def bank(self, bar, biz=None):
            """Bank the sample, but using bar and biz."""
            self.actions.append(('bank', bar, biz))
            return (bar, biz)

        @needs_read_lock
        def fail_during_read(self):
            self.actions.append('fail_during_read')
            raise TypeError('during read')

        @needs_write_lock
        def fail_during_write(self):
            self.actions.append('fail_during_write')
            raise TypeError('during write')

        if meth is not None:
            meth_read = needs_read_lock(meth)
            meth_write = needs_write_lock(meth)

    return DecoratorSample()


class TestDecoratorActions(TestCase):

    _decorator_style = None # default

    def test_read_lock_locks_and_unlocks(self):
        sam = create_decorator_sample(self._decorator_style)
        self.assertEqual('newbie', sam.frob())
        self.assertEqual(['lock_read', 'frob', 'unlock'], sam.actions)

    def test_write_lock_locks_and_unlocks(self):
        sam = create_decorator_sample(self._decorator_style)
        self.assertEqual(('bar', 'bing'), sam.bank('bar', biz='bing'))
        self.assertEqual(['lock_write', ('bank', 'bar', 'bing'), 'unlock'],
                         sam.actions)

    def test_read_lock_unlocks_during_failure(self):
        sam = create_decorator_sample(self._decorator_style)
        self.assertRaises(TypeError, sam.fail_during_read)
        self.assertEqual(['lock_read', 'fail_during_read', 'unlock'],
                         sam.actions)

    def test_write_lock_unlocks_during_failure(self):
        sam = create_decorator_sample(self._decorator_style)
        self.assertRaises(TypeError, sam.fail_during_write)
        self.assertEqual(['lock_write', 'fail_during_write', 'unlock'],
                         sam.actions)

    def test_read_lock_raises_original_error(self):
        sam = create_decorator_sample(self._decorator_style,
                                      unlock_error=SampleUnlockError())
        self.assertRaises(TypeError, sam.fail_during_read)
        self.assertEqual(['lock_read', 'fail_during_read', 'unlock_fail'],
                         sam.actions)

    def test_write_lock_raises_original_error(self):
        sam = create_decorator_sample(self._decorator_style,
                                      unlock_error=SampleUnlockError())
        self.assertRaises(TypeError, sam.fail_during_write)
        self.assertEqual(['lock_write', 'fail_during_write', 'unlock_fail'],
                         sam.actions)

    def test_read_lock_raises_unlock_error(self):
        sam = create_decorator_sample(self._decorator_style,
                                      unlock_error=SampleUnlockError())
        self.assertRaises(SampleUnlockError, sam.frob)
        self.assertEqual(['lock_read', 'frob', 'unlock_fail'], sam.actions)

    def test_write_lock_raises_unlock_error(self):
        sam = create_decorator_sample(self._decorator_style,
                                      unlock_error=SampleUnlockError())
        self.assertRaises(SampleUnlockError, sam.bank, 'bar', biz='bing')
        self.assertEqual(['lock_write', ('bank', 'bar', 'bing'),
                          'unlock_fail'], sam.actions)

    def test_read_lock_preserves_default_str_kwarg_identity(self):
        a_constant = 'A str used as a constant'
        def meth(self, param=a_constant):
            return param
        sam = create_decorator_sample(self._decorator_style, meth=meth)
        self.assertIs(a_constant, sam.meth_read())

    def test_write_lock_preserves_default_str_kwarg_identity(self):
        a_constant = 'A str used as a constant'
        def meth(self, param=a_constant):
            return param
        sam = create_decorator_sample(self._decorator_style, meth=meth)
        self.assertIs(a_constant, sam.meth_write())


class TestFastDecoratorActions(TestDecoratorActions):

    _decorator_style = 'fast'


class TestPrettyDecoratorActions(TestDecoratorActions):

    _decorator_style = 'pretty'


class TestDecoratorDocs(TestCase):
    """Test method decorators"""

    def test_read_lock_passthrough(self):
        """@needs_read_lock exposes underlying name and doc."""
        sam = create_decorator_sample(None)
        self.assertEqual('frob', sam.frob.__name__)
        self.assertDocstring('Frob the sample object', sam.frob)

    def test_write_lock_passthrough(self):
        """@needs_write_lock exposes underlying name and doc."""
        sam = create_decorator_sample(None)
        self.assertEqual('bank', sam.bank.__name__)
        self.assertDocstring('Bank the sample, but using bar and biz.',
                             sam.bank)

    def test_argument_passthrough(self):
        """Test that arguments get passed around properly."""
        sam = create_decorator_sample(None)
        sam.bank('1', biz='2')
        self.assertEqual(['lock_write',
                          ('bank', '1', '2'),
                          'unlock',
                         ], sam.actions)


class TestPrettyDecorators(TestCase):
    """Test that pretty decorators generate nice looking wrappers."""

    def get_formatted_args(self, func):
        """Return a nicely formatted string for the arguments to a function.

        This generates something like "(foo, bar=None)".
        """
        return inspect.formatargspec(*inspect.getargspec(func))

    def test__pretty_needs_read_lock(self):
        """Test that _pretty_needs_read_lock generates a nice wrapper."""

        @decorators._pretty_needs_read_lock
        def my_function(foo, bar, baz=None, biz=1):
            """Just a function that supplies several arguments."""

        self.assertEqual('my_function', my_function.__name__)
        self.assertEqual('my_function_read_locked',
                         my_function.func_code.co_name)
        self.assertEqual('(foo, bar, baz=None, biz=1)',
                         self.get_formatted_args(my_function))
        self.assertDocstring(
            'Just a function that supplies several arguments.', my_function)

    def test__fast_needs_read_lock(self):
        """Test the output of _fast_needs_read_lock."""

        @decorators._fast_needs_read_lock
        def my_function(foo, bar, baz=None, biz=1):
            """Just a function that supplies several arguments."""

        self.assertEqual('my_function', my_function.__name__)
        self.assertEqual('read_locked', my_function.func_code.co_name)
        self.assertEqual('(self, *args, **kwargs)',
                         self.get_formatted_args(my_function))
        self.assertDocstring(
            'Just a function that supplies several arguments.', my_function)

    def test__pretty_needs_write_lock(self):
        """Test that _pretty_needs_write_lock generates a nice wrapper."""

        @decorators._pretty_needs_write_lock
        def my_function(foo, bar, baz=None, biz=1):
            """Just a function that supplies several arguments."""

        self.assertEqual('my_function', my_function.__name__)
        self.assertEqual('my_function_write_locked',
                         my_function.func_code.co_name)
        self.assertEqual('(foo, bar, baz=None, biz=1)',
                         self.get_formatted_args(my_function))
        self.assertDocstring(
            'Just a function that supplies several arguments.', my_function)

    def test__fast_needs_write_lock(self):
        """Test the output of _fast_needs_write_lock."""

        @decorators._fast_needs_write_lock
        def my_function(foo, bar, baz=None, biz=1):
            """Just a function that supplies several arguments."""

        self.assertEqual('my_function', my_function.__name__)
        self.assertEqual('write_locked', my_function.func_code.co_name)
        self.assertEqual('(self, *args, **kwargs)',
                         self.get_formatted_args(my_function))
        self.assertDocstring(
            'Just a function that supplies several arguments.', my_function)

    def test_use_decorators(self):
        """Test that you can switch the type of the decorators."""
        cur_read = decorators.needs_read_lock
        cur_write = decorators.needs_write_lock
        try:
            decorators.use_fast_decorators()
            self.assertIs(decorators._fast_needs_read_lock,
                          decorators.needs_read_lock)
            self.assertIs(decorators._fast_needs_write_lock,
                          decorators.needs_write_lock)

            decorators.use_pretty_decorators()
            self.assertIs(decorators._pretty_needs_read_lock,
                          decorators.needs_read_lock)
            self.assertIs(decorators._pretty_needs_write_lock,
                          decorators.needs_write_lock)

            # One more switch to make sure it wasn't just good luck that the
            # functions pointed to the correct version
            decorators.use_fast_decorators()
            self.assertIs(decorators._fast_needs_read_lock,
                          decorators.needs_read_lock)
            self.assertIs(decorators._fast_needs_write_lock,
                          decorators.needs_write_lock)
        finally:
            decorators.needs_read_lock = cur_read
            decorators.needs_write_lock = cur_write


class TestOnlyRaisesDecorator(TestCase):

    def raise_ZeroDivisionError(self):
        1/0
        
    def test_raises_approved_error(self):
        decorator = decorators.only_raises(ZeroDivisionError)
        decorated_meth = decorator(self.raise_ZeroDivisionError)
        self.assertRaises(ZeroDivisionError, decorated_meth)

    def test_quietly_logs_unapproved_errors(self):
        decorator = decorators.only_raises(IOError)
        decorated_meth = decorator(self.raise_ZeroDivisionError)
        self.assertLogsError(ZeroDivisionError, decorated_meth)
        

