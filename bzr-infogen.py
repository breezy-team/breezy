#!/usr/bin/python

# Copyright 2005 Canonical Ltd.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""bzr-infogen.py - generate information from built-in bzr help

bzr-infogen.py creates a file with information on bzr in one of
several different output formats:

    man              man page
    bash_completion  bash completion script
    ...

Run "bzr-infogen.py --help" for usage information.
"""

# Plan (devised by jblack and ndim 2005-12-10):
#   * one bzr-infogengen.py script in top level dir right beside bzr
#   * one bzrinfogen/ directory
#   * several generator scripts like
#           bzrinfogen/gen_man_page.py
#                      gen_docbook_xml.py
# 	             gen_html.py
#                      gen_bash_completion.py
#                      gen_zsh_completion.py
#   * scripts are called by running "bzr-infogen.py --man-page" or
#     "bzr-infogen.py --bash-completion"
#   * one test case which iterates through all gen_*.py scripts and
#     tries to generate all the file types, checking that all generators
#     work
#   * those generator scripts walk through the command and option data
#     structures to extract the required information
#   * the actual names are just prototypes and subject to change


import sys
import bzrinfogen


def main(argv):
    from optparse import OptionParser
    parser = OptionParser(usage="%prog [options] OUTPUT_FORMAT")
    parser.add_option("-s", "--show-filename",
                      action="store_true", dest="show_filename", default=False,
                      help="print default filename on stdout")
    parser.add_option("-o", "--output", dest="filename",
                      help="write output to FILE", metavar="FILE")
    parser.add_option("-b", "--bzr-name", dest="bzr_name", default="bzr",
                      help="name of bzr executable", metavar="EXEC_NAME")
    parser.add_option("-q", "--quiet",
                      action="store_false", dest="verbose", default=True,
                      help="don't print status messages to stdout")
    (options, args) = parser.parse_args(argv)

    if len(args) != 2:
        parser.error("incorrect number of arguments")

    infogen_type = args[1]
    infogen_mod = bzrinfogen.get_infogen_mod(infogen_type)

    if options.filename:
        outfilename = options.filename
    else:
        outfilename = infogen_mod.get_filename(options)

    if outfilename == "-":
        outfile = sys.stdout
    else:
        outfile = open(outfilename,"w")

    if options.show_filename and (outfilename != "-"):
        print >>sys.stdout, outfilename
    
    infogen_mod.infogen(options, outfile)


if __name__ == '__main__':
    main(sys.argv)
