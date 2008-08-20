# Copyright (C) 2006, 2008 Canonical Ltd
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

"""Wrapper for readdir which returns files ordered by inode."""


import os
import sys


# the opaque C library DIR type.
cdef extern from 'errno.h':
    int ENOENT
    int ENOTDIR
    int EAGAIN
    int errno
    char *strerror(int errno)

cdef extern from 'sys/types.h':
    ctypedef long ssize_t
    ctypedef unsigned long size_t

cdef extern from 'dirent.h':
    int DT_UNKNOWN
    int DT_REG
    int DT_DIR
    int DT_FIFO
    int DT_SOCK
    int DT_CHR
    int DT_BLK
    ctypedef struct dirent:
        char d_name[256]
        # this will fail to compile if d_type is not defined.
        # if this module fails to compile, use the .py version.
        unsigned char d_type
        int d_ino
    ctypedef struct DIR
    # should be DIR *, pyrex barfs.
    DIR * opendir(char * name)
    int closedir(DIR * dir)
    dirent *readdir(DIR *dir)

_directory = 'directory'
_chardev = 'chardev'
_block = 'block'
_file = 'file'
_fifo = 'fifo'
_symlink = 'symlink'
_socket = 'socket'
_unknown = 'unknown'

dot = ord('.')

# add a typedef struct dirent dirent to workaround pyrex
cdef extern from 'readdir.h':
    pass

def read_dir(path):
    """Like os.listdir, this reads a directories contents.

    :param path: the directory to list.
    :return: a list of (sort_key, basename) tuples.
    """
    cdef DIR *the_dir
    # currently this needs a fixup - the C code says 'dirent' but should say
    # 'struct dirent'
    cdef dirent * entry
    cdef dirent sentinel
    cdef char *name
    the_dir = opendir(path)
    if NULL == the_dir:
        raise OSError(errno, strerror(errno))
    result = []
    try:
        entry = &sentinel
        while entry != NULL:
            entry = readdir(the_dir)
            if entry == NULL:
                if errno == EAGAIN:
                    # try again
                    continue
                elif errno != ENOTDIR and errno != ENOENT and errno != 0:
                    # We see ENOTDIR at the end of a normal directory.
                    # As ENOTDIR for read_dir(file) is triggered on opendir,
                    # we consider ENOTDIR to be 'no error'.
                    # ENOENT is listed as 'invalid position in the dir stream' for
                    # readdir. We swallow this for now and just keep reading.
                    raise OSError(errno, strerror(errno))
                else:
                    # done
                    continue
            name = entry.d_name
            if not (name[0] == dot and (
                (name[1] == 0) or 
                (name[1] == dot and name [2] == 0))
                ):
                result.append((entry.d_ino, entry.d_name))
    finally:
        if -1 == closedir(the_dir):
            raise OSError(errno, strerror(errno))
    return result


# vim: tw=79 ai expandtab sw=4 sts=4
