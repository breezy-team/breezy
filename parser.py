# Copyright (C) 2008 Canonical Ltd
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

"""Parser of import data into command objects.

In order to reuse existing front-ends, the stream format is a subset of
the one used by git-fast-import (as of the 1.5.4 release of git at least).
The grammar is:

  stream ::= cmd*;

  cmd ::= new_blob
        | new_commit
        | new_tag
        | reset_branch
        | checkpoint
        | progress
        ;

  new_blob ::= 'blob' lf
    mark?
    file_content;
  file_content ::= data;

  new_commit ::= 'commit' sp ref_str lf
    mark?
    ('author' sp name '<' email '>' when lf)?
    'committer' sp name '<' email '>' when lf
    commit_msg
    ('from' sp (ref_str | hexsha1 | sha1exp_str | idnum) lf)?
    ('merge' sp (ref_str | hexsha1 | sha1exp_str | idnum) lf)*
    file_change*
    lf?;
  commit_msg ::= data;

  file_change ::= file_clr
    | file_del
    | file_rnm
    | file_cpy
    | file_obm
    | file_inm;
  file_clr ::= 'deleteall' lf;
  file_del ::= 'D' sp path_str lf;
  file_rnm ::= 'R' sp path_str sp path_str lf;
  file_cpy ::= 'C' sp path_str sp path_str lf;
  file_obm ::= 'M' sp mode sp (hexsha1 | idnum) sp path_str lf;
  file_inm ::= 'M' sp mode sp 'inline' sp path_str lf
    data;

  new_tag ::= 'tag' sp tag_str lf
    'from' sp (ref_str | hexsha1 | sha1exp_str | idnum) lf
    'tagger' sp name '<' email '>' when lf
    tag_msg;
  tag_msg ::= data;

  reset_branch ::= 'reset' sp ref_str lf
    ('from' sp (ref_str | hexsha1 | sha1exp_str | idnum) lf)?
    lf?;

  checkpoint ::= 'checkpoint' lf
    lf?;

  progress ::= 'progress' sp not_lf* lf
    lf?;

     # note: the first idnum in a stream should be 1 and subsequent
     # idnums should not have gaps between values as this will cause
     # the stream parser to reserve space for the gapped values.  An
     # idnum can be updated in the future to a new object by issuing
     # a new mark directive with the old idnum.
     #
  mark ::= 'mark' sp idnum lf;
  data ::= (delimited_data | exact_data)
    lf?;

    # note: delim may be any string but must not contain lf.
    # data_line may contain any data but must not be exactly
    # delim.
  delimited_data ::= 'data' sp '<<' delim lf
    (data_line lf)*
    delim lf;

     # note: declen indicates the length of binary_data in bytes.
     # declen does not include the lf preceeding the binary data.
     #
  exact_data ::= 'data' sp declen lf
    binary_data;

     # note: quoted strings are C-style quoting supporting \c for
     # common escapes of 'c' (e..g \n, \t, \\, \") or \nnn where nnn
     # is the signed byte value in octal.  Note that the only
     # characters which must actually be escaped to protect the
     # stream formatting is: \, " and LF.  Otherwise these values
     # are UTF8.
     #
  ref_str     ::= ref;
  sha1exp_str ::= sha1exp;
  tag_str     ::= tag;
  path_str    ::= path    | '"' quoted(path)    '"' ;
  mode        ::= '100644' | '644'
                | '100755' | '755'
                | '120000'
                ;

  declen ::= # unsigned 32 bit value, ascii base10 notation;
  bigint ::= # unsigned integer value, ascii base10 notation;
  binary_data ::= # file content, not interpreted;

  when         ::= raw_when | rfc2822_when;
  raw_when     ::= ts sp tz;
  rfc2822_when ::= # Valid RFC 2822 date and time;

  sp ::= # ASCII space character;
  lf ::= # ASCII newline (LF) character;

     # note: a colon (':') must precede the numerical value assigned to
     # an idnum.  This is to distinguish it from a ref or tag name as
     # GIT does not permit ':' in ref or tag strings.
     #
  idnum   ::= ':' bigint;
  path    ::= # GIT style file path, e.g. "a/b/c";
  ref     ::= # GIT ref name, e.g. "refs/heads/MOZ_GECKO_EXPERIMENT";
  tag     ::= # GIT tag name, e.g. "FIREFOX_1_5";
  sha1exp ::= # Any valid GIT SHA1 expression;
  hexsha1 ::= # SHA1 in hexadecimal format;

     # note: name and email are UTF8 strings, however name must not
     # contain '<' or lf and email must not contain any of the
     # following: '<', '>', lf.
     #
  name  ::= # valid GIT author/committer name;
  email ::= # valid GIT author/committer email;
  ts    ::= # time since the epoch in seconds, ascii base10 notation;
  tz    ::= # GIT style timezone;

     # note: comments may appear anywhere in the input, except
     # within a data command.  Any form of the data command
     # always escapes the related input from comment processing.
     #
     # In case it is not clear, the '#' that starts the comment
     # must be the first character on that the line (an lf have
     # preceeded it).
     #
  comment ::= '#' not_lf* lf;
  not_lf  ::= # Any byte that is not ASCII newline (LF);
"""


import re
import sys

import commands
import dates
import errors


## Stream parsing ##

class LineBasedParser(object):

    def __init__(self, input):
        """A Parser that keeps track of line numbers.

        :param input: the file-like object to read from
        """
        self.input = input
        self.lineno = 0
        # Lines pushed back onto the input stream
        self._buffer = []

    def abort(self, exception, *args):
        """Raise an exception providing line number information."""
        raise exception(self.lineno, *args)

    def readline(self):
        """Get the next line including the newline or '' on EOF."""
        self.lineno += 1
        if self._buffer:
            return self._buffer.pop()
        else:
            return self.input.readline()

    def next_line(self):
        """Get the next line without the newline or None on EOF."""
        line = self.readline()
        if line:
            return line[:-1]
        else:
            return None

    def push_line(self, line):
        """Push line back onto the line buffer.
        
        :param line: the line with no trailing newline
        """
        self.lineno -= 1
        self._buffer.append(line + "\n")

    def read_bytes(self, count):
        """Read a given number of bytes from the input stream.
        
        Throws MissingBytes if the bytes are not found.

        Note: This method does not read from the line buffer.
        """
        lines = []
        left = count
        while left > 0:
            line = self.input.readline(left)
            if line:
                left -= len(line)
                lines.append(line)
            else:
                left = 0
        result = ''.join(lines)
        found = len(result)
        if found != count:
            self.abort(errors.MissingBytes, count, found)
        return result

    def read_until(self, terminator):
        """Read the input stream until the terminator is found.
        
        Throws MissingTerminator if the terminator is not found.

        Note: This method does not read from the line buffer.

        :return: the bytes read up to but excluding the terminator.
        """
        raise NotImplementedError(self.read_until)


# Regular expressions used for parsing
_WHO_AND_WHEN_RE = re.compile(r'(\w+) <(.+)> (.+)')


class ImportParser(LineBasedParser):

    def __init__(self, input, verbose=False, output=sys.stdout):
        """A Parser of import commands.

        :param input: the file-like object to read from
        :param verbose: display extra information of not
        :param output: the file-like object to write messages to (YAGNI?)
        """
        LineBasedParser.__init__(self, input)
        self.verbose = verbose
        self.output = output
        # We auto-detect the date format when a date is first encountered
        self.date_parser = None

    def iter_commands(self):
        """Iterator returning ImportCommand objects."""
        while True:
            line = self.next_line()
            if line is None:
                break
            elif len(line) == 0 or line.startswith('#'):
                continue
            # Search for commands in order of likelihood
            elif line.startswith('commit '):
                yield self._parse_commit(line[len('commit '):])
            elif line.startswith('blob'):
                yield self._parse_blob()
            elif line.startswith('progress '):
                yield commands.ProgressCommand(line[len('progress '):])
            elif line.startswith('reset '):
                yield self._parse_reset(line[len('reset '):])
            elif line.startswith('tag '):
                yield self._parse_tag(line[len('tag '):])
            elif line.startswith('checkpoint'):
                yield commands.CheckpointCommand()
            else:
                self.abort(errors.InvalidCommand, line)

    def iter_file_commands(self):
        """Iterator returning FileCommand objects.
        
        If an invalid file command is found, the line is silently
        pushed back and iteration ends.
        """
        while True:
            line = self.next_line()
            if line is None:
                break
            elif len(line) == 0 or line.startswith('#'):
                continue
            # Search for file commands in order of likelihood
            elif line.startswith('M '):
                yield self._parse_file_modify(line[2:])
            elif line.startswith('D '):
                path = self._path(line[2:])
                yield commands.FileDeleteCommand(path)
            elif line.startswith('R '):
                old, new = self._path_pair(line[2:])
                yield commands.FileRenameCommand(old, new)
            elif line.startswith('C '):
                src, dest = self._path_pair(line[2:])
                yield commands.FileRenameCommand(src, dest)
            elif line.startswith('deleteall'):
                yield commands.FileDeleteAllCommand()
            else:
                self.push_line(line)
                break

    def _parse_blob(self):
        """Parse a blob command."""
        mark = self._get_mark_if_any()
        data = self._get_data('blob')
        return commands.BlobCommand(mark, data)

    def _parse_commit(self, ref):
        """Parse a commit command."""
        mark = self._get_mark_if_any()
        author = self._get_user_info('commit', 'author', False)
        committer = self._get_user_info('commit', 'committer')
        message = self._get_data('commit', 'message')
        from_ = self._get_from()
        if from_ is not None:
            parents = [from_]
            while True:
                merge = self._get_merge()
                if merge is not None:
                    parents.append(merge)
                else:
                    break
        else:
            parents = []
        return commands.CommitCommand(ref, mark, author, committer, message,
            parents, self.iter_file_commands)

    def _parse_file_modify(self, info):
        """Parse a filemodify command within a commit.

        :param info: a string in the format "mode dataref path"
          (where dataref might be the hard-coded literal 'inline').
        """
        params = info.split(' ', 2)
        path = self._path(params[2])
        is_executable, is_symlink = self._mode(params[0])
        if is_symlink:
            kind = commands.SYMLINK_KIND
        else:
            kind = commands.FILE_KIND
        if params[1] == 'inline':
            dataref = None
            data = self._get_data('filemodify')
        else:
            dataref = params[1]
            data = None
        return commands.FileModifyCommand(path, kind, is_executable, dataref,
            data)

    def _parse_reset(self, ref):
        """Parse a reset command."""
        from_ = self._get_from()
        return commands.ResetCommand(ref, from_)

    def _parse_tag(self, name):
        """Parse a tag command."""
        from_ = self._get_from('tag')
        tagger = self._get_user_info('tag', 'tagger')
        message = self._get_data('tag', 'message')
        return commands.TagCommand(name, from_, tagger, message)

    def _get_mark_if_any(self):
        """Parse a mark section."""
        line = self.next_line()
        if line.startswith('mark :'):
            return line[len('mark :'):]
        else:
            self.push_line(line)
            return None

    def _get_from(self, required_for=None):
        """Parse a from section."""
        line = self.next_line()
        if line.startswith('from '):
            return line[len('from '):]
        elif required_for:
            self.abort(errors.MissingSection, required_for, 'from')
        else:
            self.push_line(line)
            return None

    def _get_merge(self):
        """Parse a merge section."""
        line = self.next_line()
        if line.startswith('merge '):
            return line[len('merge '):]
        else:
            self.push_line(line)
            return None

    def _get_user_info(self, cmd, section, required=True):
        """Parse a user section."""
        line = self.next_line()
        if line.startswith(section + ' '):
            return self._who_when(line[len(section + ' '):], cmd, section)
        elif required:
            self.abort(errors.MissingSection, cmd, section)
        else:
            self.push_line(line)
            return None

    def _get_data(self, required_for, section='data'):
        """Parse a data section."""
        line = self.next_line()
        if line.startswith('data '):
            rest = line[len('data '):]
            if rest.startswith('<<'):
                return self.read_until(rest[2:])
            else:
                size = int(rest)
                return self.read_bytes(size)
        else:
            self.abort(errors.MissingSection, required_for, section)

    def _who_when(self, s, cmd, section):
        """Parse who and when information from a string.
        
        :return: a tuple of (who,email,when) where who and
          email are strings and when is a datetime object
        """
        match = _WHO_AND_WHEN_RE.search(s)
        if match:
            datestr = match.group(3)
            if self.date_parser is None:
                # auto-detect the date format
                if len(datestr) == 16:
                    format = 'raw'
                elif datestr == 'now':
                    format = 'now'
                else:
                    format = 'rfc2822'
                self.date_parser = dates.DATE_PARSERS_BY_NAME[format]
            when = self.date_parser(datestr)
            return (match.group(1), match.group(2), when)
        else:
            self.abort(errors.BadFormat, cmd, section, s)

    def _path(self, s):
        """Parse a path."""
        # TODO: handle quoted paths
        return s

    def _path_pair(self, s):
        """Parse two paths separated by a space."""
        # TODO: handle quoted paths
        return tuple(s.split(' ', 1))

    def _mode(self, s):
        """Parse a file mode into executable and symlink flags.
        
        :return (is_executable, is_symlink)
        """
        # Note: Output from git-fast-export slightly different to spec
        if s in ['644', '100644', '0100644']:
            return False, False
        elif s in ['755', '100755', '0100755']:
            return True, False
        elif s == '120000':
            return False, True
        else:
            self.abort(errors.BadFormat, 'filemodify', 'mode', s)

