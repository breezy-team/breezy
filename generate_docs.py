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
"""%(prog)s - generate information from built-in bzr help

%(prog)s creates a file with information on bzr in one of
several different output formats:

    man              man page
    bash_completion  bash completion script
    ...

Examples: 

    python2.4 generated-docs.py man
    python2.4 generated-docs.py bash_completion

Run "%(prog)s --help" for the option reference.
"""

import sys
from optparse import OptionParser

import tools.doc_generate

def main(argv):
    parser = OptionParser(usage="%prog [options] OUTPUT_FORMAT")

    parser.add_option("-s", "--show-filename",
                      action="store_true", dest="show_filename", default=False,
                      help="print default filename on stdout")

    parser.add_option("-o", "--output", dest="filename", metavar="FILE",
                      help="write output to FILE")

    parser.add_option("-b", "--bzr-name",
                      dest="bzr_name", default="bzr", metavar="EXEC_NAME",
                      help="name of bzr executable")

    parser.add_option("-e", "--examples",
                      action="callback", callback=print_extended_help,
                      help="Examples of ways to call generate_doc")


    (options, args) = parser.parse_args(argv)

    if len(args) != 2:
        parser.print_help()
        sys.exit(1)

    infogen_type = args[1]
    infogen_mod = tools.doc_generate.get_module(infogen_type)

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

def print_extended_help(option, opt, value, parser):
    """ Program help examples

    Prints out the examples stored in the docstring. 

    """
        print >>sys.stdout, __doc__ % {"prog":sys.argv[0]}
        sys.exit(0)

if __name__ == '__main__':
    main(sys.argv)
