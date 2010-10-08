#!/usr/bin/python

# Copyright 2009-2010 Canonical Ltd.
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

"""Generate doc/en/release-notes/index.txt from the per-series NEWS files.

NEWS files are kept in doc/en/release-notes/, one file per series, e.g.
doc/en/release-notes/bzr-2.3.txt
"""

# XXX: add test_source test that latest doc/en/release-notes/bzr-*.txt has the
# NEWS file-id (so that merges of new work will tend to always land new NEWS
# entries in the latest series).


import os.path
import re
import sys
from optparse import OptionParser


preamble = """\
####################
Bazaar Release Notes
####################


.. toctree::
   :maxdepth: 1

"""


def natural_sort_key(file_name):
    """Split 'aaa-N.MMbbb' into ('aaa-', N, '.' MM, 'bbb')
    
    e.g. 1.10b1 will sort as greater than 1.2::

        >>> natural_sort_key('bzr-1.10b1.txt') > natural_sort_key('bzr-1.2.txt')
        True
    """
    parts = re.findall(r'(?:[0-9]+|[^0-9]+)', file_name)
    result = []
    for part in parts:
        if re.match('^[0-9]+$', part) is not None:
            part = int(part)
        result.append(part)
    return tuple(result)


def main(argv):
    # Check usage
    parser = OptionParser(usage="%prog OUTPUT_FILE NEWS_FILE [NEWS_FILE ...]")
    (options, args) = parser.parse_args(argv)
    if len(args) < 2:
        parser.print_help()
        sys.exit(1)

    # Open the files and do the work
    out_file_name = args[0]
    news_file_names = map(os.path.basename, args[1:])
    news_file_names = sorted(news_file_names, key=natural_sort_key,
        reverse=True)

    out_file = open(out_file_name, 'w')
    try:
        out_file.write(preamble)
        for news_file_name in news_file_names:
            if not news_file_name.endswith('.txt'):
                raise AssertionError(
                    'NEWS file %s does not have .txt extension.'
                    % (news_file_name,))
            doc_name = news_file_name[:-4]
            link_text = doc_name.replace('-', ' ')
            out_file.write('   %s <%s>\n' % (link_text, doc_name))
    finally:
        out_file.close()


if __name__ == '__main__':
    main(sys.argv[1:])
