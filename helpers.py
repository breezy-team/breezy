# Copyright (C) 2008 Canonical Ltd
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

"""Miscellaneous useful stuff."""


def single_plural(n, single, plural):
    """Return a single or plural form of a noun based on number."""
    if n == 1:
        return single
    else:
        return plural


def defines_to_dict(defines):
    """Convert a list of definition strings to a dictionary."""
    if defines is None:
        return None
    result = {}
    for define in defines:
        kv = define.split('=', 1)
        if len(kv) == 1:
            result[define.strip()] = 1
        else:
            result[kv[0].strip()] = kv[1].strip()
    return result


def invert_dict(d):
    """Invert a dictionary with keys matching each value turned into a list."""
    # Based on recipe from ASPN
    result = {}
    for k, v in d.iteritems():
        keys = result.setdefault(v, [])
        keys.append(k)
    return result


def invert_dictset(d):
    """Invert a dictionary with keys matching a set of values, turned into lists."""
    # Based on recipe from ASPN
    result = {}
    for k, c in d.iteritems():
        for v in c:
            keys = result.setdefault(v, [])
            keys.append(k)
    return result


def _common_path_and_rest(l1, l2, common=[]):
    # From http://code.activestate.com/recipes/208993/
    if len(l1) < 1: return (common, l1, l2)
    if len(l2) < 1: return (common, l1, l2)
    if l1[0] != l2[0]: return (common, l1, l2)
    return _common_path_and_rest(l1[1:], l2[1:], common+[l1[0]])


def common_path(path1, path2):
    """Find the common bit of 2 paths."""
    return ''.join(_common_path_and_rest(path1, path2)[0])


def common_directory(paths):
    """Find the deepest common directory of a list of paths.
    
    :return: if no paths are provided, None is returned;
      if there is no common directory, '' is returned;
      otherwise the common directory with a trailing / is returned.
    """
    from bzrlib import osutils
    def get_dir_with_slash(path):
        if path == '' or path.endswith('/'):
            return path
        else:
            dirname, basename = osutils.split(path)
            if dirname == '':
                return dirname
            else:
                return dirname + '/'

    if not paths:
        return None
    elif len(paths) == 1:
        return get_dir_with_slash(paths[0])
    else:
        common = common_path(paths[0], paths[1])
        for path in paths[2:]:
            common = common_path(common, path)
        return get_dir_with_slash(common)


def escape_commit_message(message):
    """Replace xml-incompatible control characters."""
    # This really ought to be provided by bzrlib.
    # Code copied from bzrlib.commit.
    
    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    import re
    message, _ = re.subn(
        u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
        lambda match: match.group(0).encode('unicode_escape'),
        message)
    return message


def binary_stream(stream):
    """Ensure a stream is binary on Windows.

    :return: the stream
    """
    try:
        import os
        if os.name == 'nt':
            fileno = getattr(stream, 'fileno', None)
            if fileno:
                no = fileno()
                if no >= 0:     # -1 means we're working as subprocess
                    import msvcrt
                    msvcrt.setmode(no, os.O_BINARY)
    except ImportError:
        pass
    return stream
