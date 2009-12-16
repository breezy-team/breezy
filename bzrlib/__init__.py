# Copyright (C) 2005, 2006, 2007, 2008, 2009 Canonical Ltd
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

"""bzr library"""

import time

# Keep track of when bzrlib was first imported, so that we can give rough
# timestamps relative to program start in the log file kept by bzrlib.trace.
_start_time = time.time()

import sys
if getattr(sys, '_bzr_lazy_regex', False):
    # The 'bzr' executable sets _bzr_lazy_regex.  We install the lazy regex
    # hack as soon as possible so that as much of the standard library can
    # benefit, including the 'string' module.
    del sys._bzr_lazy_regex
    import bzrlib.lazy_regex
    bzrlib.lazy_regex.install_lazy_compile()

from bzrlib.osutils import get_user_encoding


IGNORE_FILENAME = ".bzrignore"


# XXX: Deprecated as of bzr-1.17 use osutils.get_user_encoding() directly
user_encoding = get_user_encoding()


__copyright__ = "Copyright 2005, 2006, 2007, 2008, 2009 Canonical Ltd."

# same format as sys.version_info: "A tuple containing the five components of
# the version number: major, minor, micro, releaselevel, and serial. All
# values except releaselevel are integers; the release level is 'alpha',
# 'beta', 'candidate', or 'final'. The version_info value corresponding to the
# Python version 2.0 is (2, 0, 0, 'final', 0)."  Additionally we use a
# releaselevel of 'dev' for unreleased under-development code.

version_info = (2, 0, 3, 'final', 0)

# API compatibility version: bzrlib is currently API compatible with 1.15.
api_minimum_version = (1, 17, 0)

def _format_version_tuple(version_info):
    """Turn a version number 2, 3 or 5-tuple into a short string.

    This format matches <http://docs.python.org/dist/meta-data.html>
    and the typical presentation used in Python output.

    This also checks that the version is reasonable: the sub-release must be
    zero for final releases.

    >>> print _format_version_tuple((1, 0, 0, 'final', 0))
    1.0.0
    >>> print _format_version_tuple((1, 2, 0, 'dev', 0))
    1.2.0dev
    >>> print bzrlib._format_version_tuple((1, 2, 0, 'dev', 1))
    1.2.0dev1
    >>> print _format_version_tuple((1, 1, 1, 'candidate', 2))
    1.1.1rc2
    >>> print bzrlib._format_version_tuple((2, 1, 0, 'beta', 1))
    2.1.0b1
    >>> print _format_version_tuple((1, 4, 0))
    1.4.0
    >>> print _format_version_tuple((1, 4))
    1.4
    >>> print bzrlib._format_version_tuple((2, 1, 0, 'final', 1))
    Traceback (most recent call last):
    ...
    ValueError: version_info (2, 1, 0, 'final', 1) not valid
    >>> print _format_version_tuple((1, 4, 0, 'wibble', 0))
    Traceback (most recent call last):
    ...
    ValueError: version_info (1, 4, 0, 'wibble', 0) not valid
    """
    if len(version_info) == 2:
        main_version = '%d.%d' % version_info[:2]
    else:
        main_version = '%d.%d.%d' % version_info[:3]
    if len(version_info) <= 3:
        return main_version

    release_type = version_info[3]
    sub = version_info[4]

    # check they're consistent
    if release_type == 'final' and sub == 0:
        sub_string = ''
    elif release_type == 'dev' and sub == 0:
        sub_string = 'dev'
    elif release_type == 'dev':
        sub_string = 'dev' + str(sub)
    elif release_type in ('alpha', 'beta'):
        sub_string = release_type[0] + str(sub)
    elif release_type == 'candidate':
        sub_string = 'rc' + str(sub)
    else:
        raise ValueError("version_info %r not valid" % (version_info,))

    return main_version + sub_string


__version__ = _format_version_tuple(version_info)
version_string = __version__


def test_suite():
    import tests
    return tests.test_suite()
