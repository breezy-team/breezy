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
    >>> n1 = next(gen)
    >>> n2 = next(gen)
    >>> type(n1)
    <class 'str'>
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

    >>> n1 = next(generate_unicode_names())
    >>> enc = next(generate_unicode_encodings(universal_encoding=True))
    >>> enc2 = next(generate_unicode_encodings(universal_encoding=False))
    >>> n1.encode(enc).decode(enc) == n1
    True
    >>> try:
    ...   n1.encode(enc2).decode(enc2)
    ... except UnicodeError:
    ...   print('fail')
    fail
    """
    # TODO: check they're supported on this platform?
    if universal_encoding is not None:
        e = [n for (n, u) in interesting_encodings if u == universal_encoding]
    else:
        e = [n for (n, u) in interesting_encodings]
    return itertools.cycle(iter(e))


class RecordingContextManager(object):
    """A context manager that records."""

    def __init__(self):
        self._calls = []

    def __enter__(self):
        self._calls.append('__enter__')
        return self  # This is bound to the 'as' clause in a with statement.

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._calls.append('__exit__')
        return False  # propogate exceptions.


def build_branch_with_non_ancestral_rev(branch_builder):
    """Builds a branch with a rev not in the ancestry of the tip.

    This is the revision graph::

      rev-2
        |
      rev-1
        |
      (null)

    The branch tip is 'rev-1'.  'rev-2' is present in the branch's repository,
    but is not part of rev-1's ancestry.

    :param branch_builder: A BranchBuilder (e.g. from
        TestCaseWithMemoryTransport.make_branch_builder).
    :returns: the new branch
    """
    # Make a sequence of two commits
    rev1 = branch_builder.build_commit(message="Rev 1")
    rev2 = branch_builder.build_commit(message="Rev 2")
    # Move the branch tip back to the first commit
    source = branch_builder.get_branch()
    source.set_last_revision_info(1, rev1)
    return source, rev1, rev2


def make_branch_and_populated_tree(testcase):
    """Make a simple branch and tree.

    The tree holds some added but uncommitted files.
    """
    # TODO: Either accept or return the names of the files, so the caller
    # doesn't need to be bound to the particular files created? -- mbp
    # 20110705
    tree = testcase.make_branch_and_tree('t')
    testcase.build_tree_contents([('t/hello', b'hello world')])
    tree.add(['hello'], ids=[b'hello-id'])
    return tree


class TimeoutFixture(object):
    """Kill a test with sigalarm if it runs too long.

    Only works on Unix at present.
    """

    def __init__(self, timeout_secs):
        import signal
        self.timeout_secs = timeout_secs
        self.alarm_fn = getattr(signal, 'alarm', None)

    def setUp(self):
        if self.alarm_fn is not None:
            self.alarm_fn(self.timeout_secs)

    def cleanUp(self):
        if self.alarm_fn is not None:
            self.alarm_fn(0)
