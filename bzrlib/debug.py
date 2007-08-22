# Copyright (C) 2005, 2006 Canonical Ltd
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


debug_flags = set()
"""Set of flags that enable different debug behaviour.

These are set with eg ``-Dlock`` on the bzr command line.

Options include:
 
 * evil - capture call sites that do expensive or badly-scaling operations.
 * error - show stack traces for all top level exceptions
 * hooks 
 * hpss - trace smart protocol requests and responses
 * index - trace major index operations
 * lock - trace when lockdir locks are taken or released

"""
