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

# Plan (devised by jblack and ndim 2005-12-10):
#   * one generate_doc.py script in top level dir right beside bzr
#   * one tools/doc_generate/ directory (python module)
#     We did not put the stuff into bzrlib because we thought
#     that all this stuff doesn't need to get loaded every time you run bzr.
#     However, I'm not sure that is actually true (ndim 2005-12-11).
#   * several generator scripts like
#           tools/doc_generate/autodoc_man_page.py
#                              autodoc_docbook_xml.py
#                              autodoc_html.py
#                              autodoc_bash_completion.py
#                              autodoc_zsh_completion.py
#   * scripts are called by running something like
#     "python2.4 generated_docs.py --man-page"         or
#     "python2.4 generated_docs.py --bash-completion"   or
#     "pytohn2.4 generated_docs.py --all"
#     
#   * one test case which iterates through all gen_*.py scripts and
#     tries to generate all the file types, checking that all generators
#     work (we'll let bzrinfogen/__init__.py provide the list to walk through)
#   * those generator scripts walk through the command and option data
#     structures to extract the required information
#   * the actual names are just prototypes and subject to change


import sys
import tools.doc_generate

def main(argv):
    from optparse import OptionParser
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
        print >>sys.stdout, __doc__ % {"prog":sys.argv[0]}
        sys.exit(0)

if __name__ == '__main__':
    main(sys.argv)
