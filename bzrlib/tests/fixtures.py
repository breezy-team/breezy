# Copyright (C) 2010 Canonical Ltd
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


"""Fixtures that can be used within tests.

Fixtures can be created during a test as a way to separate out creation of
objects to test.  Fixture objects can hold some state so that different 
objects created during a test instance can be related.  Normally a fixture
should live only for the duration of a single test, and its tearDown method
should be passed to `addCleanup` on the test.
"""


import itertools


def generate_unicode_names():
    """Generate a sequence of arbitrary unique unicode names.
    
    By default they are not representable in ascii.
    
    >>> gen = generate_unicode_names()
    >>> n1 = gen.next()
    >>> n2 = gen.next()
    >>> type(n1)
    <type 'unicode'>
    >>> n1 == n2
    False
    >>> n1.encode('ascii', 'replace') == n1
    False
    """
    # include a mathematical symbol unlikely to be in 8-bit encodings
    return (u"\N{SINE WAVE}%d" % x for x in itertools.count())


interesting_encodings = [
    ('iso-8859-1', False),
    ('ascii', False),
    ('cp850', False),
    ('utf-8', True),
    ('ucs-2', True),
    ]


def generate_unicode_encodings(universal_encoding=None):
    """Return a generator of unicode encoding names.

    These can be passed to Python encode/decode/etc.
    
    :param universal_encoding: True/False/None tristate to say whether the
        generated encodings either can or cannot encode all unicode 
        strings.

    >>> n1 = generate_unicode_names().next()
    >>> enc = generate_unicode_encodings(universal_encoding=True).next()
    >>> enc2 = generate_unicode_encodings(universal_encoding=False).next()
    >>> n1.encode(enc).decode(enc) == n1
    True
    >>> try:
    ...   n1.encode(enc2).decode(enc2)
    ... except UnicodeError:
    ...   print 'fail'
    fail
    """
    # TODO: check they're supported on this platform?
    if universal_encoding is not None:
        e = [n for (n, u) in interesting_encodings if u == universal_encoding]
    else:
        e = [n for (n, u) in interesting_encodings]
    return itertools.cycle(iter(e))
