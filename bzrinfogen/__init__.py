#!/usr/bin/python

# Copyright 2005 Canonical Ltd.
# Written by Hans Ulrich Niedermann

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

"""bzrinitgen/__init__.py - main program for bzr information generation stuff

"""


import sys


def get_infogen_mod(infogen_type):
    mod_name = "bzrinfogen.big_%s" % (infogen_type)
    mod = __import__(mod_name)
    components = mod_name.split('.')
    for comp in components[1:]:
        mod = getattr(mod, comp)
    return mod


def main(argv):
    from optparse import OptionParser
    parser = OptionParser(usage="%prog [options] OUTPUT_FORMAT")
    parser.add_option("-s", "--show-filename",
                      action="store_true", dest="show_filename", default=False,
                      help="print default filename on stdout")
    parser.add_option("-f", "--file", dest="filename",
                      help="write report to FILE", metavar="FILE")
    parser.add_option("-b", "--bzr-name", dest="bzr_name", default="bzr",
                      help="name of bzr executable", metavar="EXEC_NAME")
    parser.add_option("-q", "--quiet",
                      action="store_false", dest="verbose", default=True,
                      help="don't print status messages to stdout")
    (options, args) = parser.parse_args(argv)

    if len(args) != 2:
        parser.error("incorrect number of arguments")

    infogen_type = args[1]
    infogen_mod = get_infogen_mod(infogen_type)

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
