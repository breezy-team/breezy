#!/usr/bin/python3

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
doc/en/release-notes/brz-2.3.txt
"""

# XXX: add test_source test that latest doc/en/release-notes/brz-*.txt has the
# NEWS file-id (so that merges of new work will tend to always land new NEWS
# entries in the latest series).

import os.path
import re
import sys
from optparse import OptionParser

preamble_plain = """\
####################
Breezy Release Notes
####################


.. contents:: List of Releases
   :depth: 2

"""

preamble_sphinx = """\
####################
Breezy Release Notes
####################


.. toctree::
   :maxdepth: 2

"""


def natural_sort_key(file_name):
    """Split 'aaa-N.MMbbb' into ('aaa-', N, '.' MM, 'bbb').

    e.g. 1.10b1 will sort as greater than 1.2::

        >>> natural_sort_key('brz-1.10b1.txt') > natural_sort_key('brz-1.2.txt')
        True
    """
    file_name = os.path.basename(file_name)
    parts = re.findall(r"(?:[0-9]+|[^0-9]+)", file_name)
    result = []
    for part in parts:
        if re.match("^[0-9]+$", part) is not None:
            part = int(part)
        result.append(part)
    return tuple(result)


def output_news_file_sphinx(out_file, news_file_name):
    news_file_name = os.path.basename(news_file_name)
    if not news_file_name.endswith(".txt"):
        raise AssertionError(
            "NEWS file {} does not have .txt extension.".format(news_file_name)
        )
    doc_name = news_file_name[:-4]
    link_text = doc_name.replace("-", " ")
    out_file.write("   {} <{}>\n".format(link_text, doc_name))


def output_news_file_plain(out_file, news_file_name):
    with open(news_file_name) as f:
        lines = f.readlines()
    title = os.path.basename(news_file_name)[len("brz-") : -len(".txt")]
    for line in lines:
        if line == "####################\n":
            line = "#" * len(title) + "\n"
        elif line == "Breezy Release Notes\n":
            line = title + "\n"
        elif line == ".. toctree::\n":
            continue
        elif line == "   :maxdepth: 1\n":
            continue
        out_file.write(line)
    out_file.write("\n\n")


def main(argv):
    # Check usage
    parser = OptionParser(usage="%prog OUTPUT_FILE NEWS_FILE [NEWS_FILE ...]")
    (_options, args) = parser.parse_args(argv)
    if len(args) < 2:
        parser.print_help()
        sys.exit(1)

    # Open the files and do the work
    out_file_name = args[0]
    news_file_names = sorted(args[1:], key=natural_sort_key, reverse=True)

    if os.path.basename(out_file_name) == "index.txt":
        preamble = preamble_sphinx
        output_news_file = output_news_file_sphinx
    else:
        preamble = preamble_plain
        output_news_file = output_news_file_plain

    with open(out_file_name, "w") as out_file:
        out_file.write(preamble)
        for news_file_name in news_file_names:
            output_news_file(out_file, news_file_name)


if __name__ == "__main__":
    main(sys.argv[1:])
