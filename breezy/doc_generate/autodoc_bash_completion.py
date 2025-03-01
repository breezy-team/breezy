# Copyright (C) 2005 Canonical Ltd

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

"""bash_completion.py - create bash completion script from built-in brz help"""

import breezy
import breezy.commands
import breezy.help
from breezy.doc_generate import get_autodoc_datetime


def get_filename(options):
    return "%s.bash_completion" % (options.brz_name)


def infogen(options, outfile):
    d = get_autodoc_datetime()
    params = {
        "brzcmd": options.brz_name,
        "datestamp": d.strftime("%Y-%m-%d"),
        "timestamp": d.strftime("%Y-%m-%d %H:%M:%S +0000"),
        "version": breezy.__version__,
    }

    outfile.write(preamble % params)


preamble = """\
# bash completion functions for for Breezy (%(brzcmd)s)
#
# Large parts of this file are autogenerated from the internal
# Breezy documentation and data structures.
#
# Generation time: %(timestamp)s
"""
