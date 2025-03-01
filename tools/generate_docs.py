#!/usr/bin/python3

# Copyright 2005 Canonical Ltd.
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

"""%(prog)s - generate information from built-in brz help.

%(prog)s creates a file with information on brz in one of
several different output formats:

    man              man page
    bash_completion  bash completion script
    ...

Examples:
    python generated-docs.py man
    python generated-docs.py bash_completion

Run "%(prog)s --help" for the option reference.
"""

import os
import sys
from optparse import OptionParser

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from contextlib import ExitStack

import breezy
from breezy import commands, doc_generate


def main(argv):
    parser = OptionParser(
        usage="""%prog [options] OUTPUT_FORMAT

Available OUTPUT_FORMAT:

    man              man page
    rstx             man page in ReStructuredText format
    bash_completion  bash completion script"""
    )

    parser.add_option(
        "-s",
        "--show-filename",
        action="store_true",
        dest="show_filename",
        default=False,
        help="print default filename on stdout",
    )

    parser.add_option(
        "-o", "--output", dest="filename", metavar="FILE", help="write output to FILE"
    )

    parser.add_option(
        "-b",
        "--brz-name",
        dest="brz_name",
        default="brz",
        metavar="EXEC_NAME",
        help="name of brz executable",
    )

    parser.add_option(
        "-e",
        "--examples",
        action="callback",
        callback=print_extended_help,
        help="Examples of ways to call generate_doc",
    )

    (options, args) = parser.parse_args(argv)

    if len(args) != 2:
        parser.print_help()
        sys.exit(1)

    with breezy.initialize(), ExitStack() as es:
        # Import breezy.bzr for format registration, see <http://pad.lv/956860>
        from breezy import bzr as _  # noqa: F401

        commands.install_bzr_command_hooks()
        infogen_type = args[1]
        infogen_mod = doc_generate.get_module(infogen_type)
        if options.filename:
            outfilename = options.filename
        else:
            outfilename = infogen_mod.get_filename(options)
        if outfilename == "-":
            outfile = sys.stdout
        else:
            outfile = es.enter_context(open(outfilename, "w"))
        if options.show_filename and (outfilename != "-"):
            sys.stdout.write(outfilename)
            sys.stdout.write("\n")
        infogen_mod.infogen(options, outfile)


def print_extended_help(option, opt, value, parser):
    """Program help examples.

    Prints out the examples stored in the docstring.

    """
    sys.stdout.write(__doc__ % {"prog": sys.argv[0]})
    sys.stdout.write("\n")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv)
