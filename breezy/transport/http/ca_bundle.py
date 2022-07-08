# Copyright (C) 2007 Canonical Ltd
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

"""Auto-detect of CA bundle for SSL connections"""

import os
import sys
from ...trace import mutter


_ca_path = None


def get_ca_path(use_cache=True):
    """Return location of CA bundle"""
    global _ca_path

    if _ca_path is not None and use_cache:
        return _ca_path

    # Find CA bundle for SSL
    # Reimplementation in Python the magic of curl command line tool
    # from "Details on Server SSL Certificates"
    # http://curl.haxx.se/docs/sslcerts.html
    #
    # 4. If you're using the curl command line tool, you can specify your own
    #    CA cert path by setting the environment variable CURL_CA_BUNDLE to the
    #    path of your choice.
    #
    #    If you're using the curl command line tool on Windows, curl will
    #    search for a CA cert file named "curl-ca-bundle.crt" in these
    #    directories and in this order:
    #      1. application's directory
    #      2. current working directory
    #      3. Windows System directory (e.g. C:\windows\system32)
    #      4. Windows Directory (e.g. C:\windows)
    #      5. all directories along %PATH%
    #
    # NOTES:
    #   bialix: Windows directories usually listed in PATH env variable
    #   j-a-meinel: bzr should not look in current working dir

    path = os.environ.get('CURL_CA_BUNDLE')
    if not path and sys.platform == 'win32':
        dirs = [os.path.realpath(os.path.dirname(sys.argv[0]))]     # app dir
        paths = os.environ.get('PATH')
        if paths:
            # don't include the cwd in the search
            paths = [i for i in paths.split(os.pathsep) if i not in ('', '.')]
            dirs.extend(paths)
        for d in dirs:
            fname = os.path.join(d, "curl-ca-bundle.crt")
            if os.path.isfile(fname):
                path = fname
                break
    if path:
        mutter('using CA bundle: %r', path)
    else:
        path = ''

    if use_cache:
        _ca_path = path

    return path
