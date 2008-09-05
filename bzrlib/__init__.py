# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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

"""bzr library"""

import time

# Keep track of when bzrlib was first imported, so that we can give rough
# timestamps relative to program start in the log file kept by bzrlib.trace.
_start_time = time.time()

from bzrlib.osutils import get_user_encoding


IGNORE_FILENAME = ".bzrignore"


# XXX: Compatibility. This should probably be deprecated
user_encoding = get_user_encoding()


__copyright__ = "Copyright 2005, 2006, 2007, 2008 Canonical Ltd."

# same format as sys.version_info: "A tuple containing the five components of
# the version number: major, minor, micro, releaselevel, and serial. All
# values except releaselevel are integers; the release level is 'alpha',
# 'beta', 'candidate', or 'final'. The version_info value corresponding to the
# Python version 2.0 is (2, 0, 0, 'final', 0)."  Additionally we use a
# releaselevel of 'dev' for unreleased under-development code.

version_info = (1, 6, 1, 'final', 0)


# API compatibility version: bzrlib is currently API compatible with 1.6.
api_minimum_version = (1, 6, 0)

def _format_version_tuple(version_info):
    """Turn a version number 3-tuple or 5-tuple into a short string.

    This format matches <http://docs.python.org/dist/meta-data.html>
    and the typical presentation used in Python output.

    This also checks that the version is reasonable: the sub-release must be
    zero for final releases, and non-zero for alpha, beta and preview.

    >>> print _format_version_tuple((1, 0, 0, 'final', 0))
    1.0
    >>> print _format_version_tuple((1, 2, 0, 'dev', 0))
    1.2dev
    >>> print _format_version_tuple((1, 1, 1, 'candidate', 2))
    1.1.1rc2
    >>> print _format_version_tuple((1, 4, 0))
    1.4
    """
    if version_info[2] == 0:
        main_version = '%d.%d' % version_info[:2]
    else:
        main_version = '%d.%d.%d' % version_info[:3]
    if len(version_info) <= 3:
        return main_version

    __release_type = version_info[3]
    __sub = version_info[4]

    # check they're consistent
    if __release_type == 'final' and __sub == 0:
        __sub_string = ''
    elif __release_type == 'dev' and __sub == 0:
        __sub_string = 'dev'
    elif __release_type in ('alpha', 'beta') and __sub != 0:
        __sub_string = __release_type[0] + str(__sub)
    elif __release_type == 'candidate' and __sub != 0:
        __sub_string = 'rc' + str(__sub)
    else:
        raise AssertionError("version_info %r not valid" % version_info)

    version_string = '%d.%d.%d.%s.%d' % version_info
    return main_version + __sub_string

__version__ = _format_version_tuple(version_info)
version_string = __version__


# allow bzrlib plugins to be imported.
import bzrlib.plugin
bzrlib.plugin.set_plugins_path()


def test_suite():
    import tests
    return tests.test_suite()
