#!/usr/bin/python

# Copyright 2009 Canonical Ltd.
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

import os
import sys
from optparse import OptionParser

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def split_into_topics(lines, out_file, out_dir):
    """Split a large NEWS file into topics, one per release.

    Releases are detected by matching headings that look like
    release names. Topics are created with matching names
    replacing spaces with dashes.
    """
    topic_file = None
    for index, line in enumerate(lines):
        maybe_new_topic = line[:4] in ['bzr ', 'bzr-0',]
        if maybe_new_topic and lines[index + 1].startswith('####'):
            release = line.strip()
            if topic_file is None:
                # First topic found
                out_file.write(".. toctree::\n   :maxdepth: 1\n\n")
            else:
                # close the current topic
                topic_file.close()
            topic_file = open_topic_file(out_file, out_dir, release)
        elif topic_file:
            topic_file.write(line)
        else:
            # Still in the header - dump content straight to output
            out_file.write(line)


def open_topic_file(out_file, out_dir, release):
    topic_name = release.replace(' ', '-')
    out_file.write("   %s\n" % (topic_name,))
    topic_path = os.path.join(out_dir, "%s.txt" % (topic_name,))
    result = open(topic_path, 'w')
    result.write("%s\n" % (release,))
    return result


def main(argv):
    # Check usage
    parser = OptionParser(usage="%prog SOURCE DESTINATION")
    (options, args) = parser.parse_args(argv)
    if len(args) != 2:
        parser.print_help()
        sys.exit(1)

    # Open the files and do the work
    infile_name = args[0]
    outfile_name = args[1]
    outdir = os.path.dirname(outfile_name)
    infile = open(infile_name, 'r')
    try:
        lines = infile.readlines()
    finally:
        infile.close()
    outfile = open(outfile_name, 'w')
    try:
        split_into_topics(lines, outfile, outdir)
    finally:
        outfile.close()


if __name__ == '__main__':
    main(sys.argv[1:])
