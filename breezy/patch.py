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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from __future__ import absolute_import

import errno
import os
from subprocess import Popen, PIPE

from .errors import NoDiff3
from .textfile import check_text_path

"""Diff and patch functionality"""

__docformat__ = "restructuredtext"


_do_close_fds = True
if os.name == 'nt':
    _do_close_fds = False


def write_to_cmd(args, input=""):
    """Spawn a process, and wait for the result

    If the process is killed, an exception is raised

    :param args: The command line, the first entry should be the program name
    :param input: [optional] The text to send the process on stdin
    :return: (stdout, stderr, status)
    """
    process = Popen(args, bufsize=len(input), stdin=PIPE, stdout=PIPE,
                    stderr=PIPE, close_fds=_do_close_fds)
    stdout, stderr = process.communicate(input)
    status = process.wait()
    if status < 0:
        raise Exception("%s killed by signal %i" (args[0], -status))
    return stdout, stderr, status


def patch(patch_contents, filename, output_filename=None, reverse=False):
    """Apply a patch to a file, to produce another output file.  This is should
    be suitable for our limited purposes.

    :param patch_contents: The contents of the patch to apply
    :type patch_contents: str
    :param filename: the name of the file to apply the patch to
    :type filename: str
    :param output_filename: The filename to produce.  If None, file is \
    modified in-place
    :type output_filename: str or NoneType
    :param reverse: If true, apply the patch in reverse
    :type reverse: bool
    :return: 0 on success, 1 if some hunks failed
    """
    args = ["patch", "-f", "-s", "--posix", "--binary"]
    if reverse:
        args.append("--reverse")
    if output_filename is not None:
        args.extend(("-o", output_filename))
    args.append(filename)
    stdout, stderr, status = write_to_cmd(args, patch_contents)
    return status


def diff3(out_file, mine_path, older_path, yours_path):
    def add_label(args, label):
        args.extend(("-L", label))
    check_text_path(mine_path)
    check_text_path(older_path)
    check_text_path(yours_path)
    args = ['diff3', "-E", "--merge"]
    add_label(args, "TREE")
    add_label(args, "ANCESTOR")
    add_label(args, "MERGE-SOURCE")
    args.extend((mine_path, older_path, yours_path))
    try:
        output, stderr, status = write_to_cmd(args)
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise NoDiff3
        else:
            raise
    if status not in (0, 1):
        raise Exception(stderr)
    f = open(out_file, 'wb')
    try:
        f.write(output)
    finally:
        f.close()
    return status
