#! /usr/bin/env python
# vim: fileencoding=utf-8
#
# Copyright (c) 2008 Adeodato Simó (dato@net.com.org.es)
#
# This software may be used and distributed according to the terms
# of the MIT License, incorporated herein by reference.

"""bzr frontend for git-fast-import(1).

This program generates a stream from a bzr branch in the format required by
git-fast-import(1). It preserves merges correctly, even merged branches with
no common history (`bzr merge -r 0..-1`).

To import several unmerged but related branches into the same repository, use
the --{export,import}-marks options, and specify a name for !master branches.
For example:

    % bzr-fast-export --export-marks=marks.bzr project.dev |
          GIT_DIR=project/.git git-fast-import --export-marks=marks.git

    % bzr-fast-export --import-marks=marks.bzr -b other project.other |
          GIT_DIR=project/.git git-fast-import --import-marks=marks.git
"""

# There is a bug in git 1.5.4.3 and older by which unquoting a string consumes
# one extra character. Set this variable to True to work-around it. It only
# happens when renaming a file whose name contains spaces and/or quotes, and
# the symptom is:
#   % git-fast-import
#   fatal: Missing space after source: R "file 1.txt" file 2.txt
# http://git.kernel.org/?p=git/git.git;a=commit;h=c8744d6a8b27115503565041566d97c21e722584
GIT_FAST_IMPORT_NEEDS_EXTRA_SPACE_AFTER_QUOTE = False

# TODO: progress

# TODO: if a new_git_branch below gets merged repeteadly, the tip of the branch
# is not updated (because the parent of commit is already merged, so we don't
# set new_git_branch to the previously used name)

##

import os
import re
import sys
import optparse
from email.Utils import quote, parseaddr

import bzrlib.branch
import bzrlib.revision

REVID_TO_MARK = {}

def main():
    options, arguments = parse_options()

    if options.import_marks:
        branches, revid_to_mark = import_marks(options.import_marks)
        _branch_names.update(branches)
        REVID_TO_MARK.update(revid_to_mark)

    branch = bzrlib.branch.Branch.open_containing(arguments[0])[0]

    branch.repository.lock_read()
    try:
        for revid in branch.revision_history():
            if revid not in REVID_TO_MARK:
                emit_commit(revid, branch, options.git_branch)
    finally:
        branch.repository.unlock()

    if branch.supports_tags():
        emit_tags(branch)

    if options.export_marks:
        export_marks(options.export_marks, _branch_names, REVID_TO_MARK)

##

def emit_commit(revid, branch, git_branch):
    revobj = branch.repository.get_revision(revid)
    mark = REVID_TO_MARK[revid] = len(REVID_TO_MARK) + 1
    stream = 'commit refs/heads/%s\nmark :%d\n' % (git_branch, mark)

    rawdate = '%d %s' % (int(revobj.timestamp), '%+03d%02d' % (
                revobj.timezone / 3600, (revobj.timezone / 60) % 60))

    author = revobj.get_apparent_author()
    if author != revobj.committer:
        stream += 'author %s %s\n' % (
                name_with_angle_brackets(author), rawdate)

    stream += 'committer %s %s\n' % (
            name_with_angle_brackets(revobj.committer), rawdate)

    stream += 'data %d\n%s\n' % (
            len(revobj.message.encode('utf-8')), revobj.message)

    nparents = len(revobj.parent_ids)

    if nparents >= 1:
        parent = revobj.parent_ids[0]
        stream += 'from :%d\n' % (REVID_TO_MARK[parent],)
        if nparents == 2:
            pending = []
            current = revobj.parent_ids[1]
            new_git_branch = git_branch
            while current not in REVID_TO_MARK:
                pending.append(current)
                r = branch.repository.get_revision(current)
                if r.parent_ids:
                    current = r.parent_ids[0]
                else:
                    # user did bzr merge -r 0..-1
                    new_git_branch = next_available_branch_name(
                            r.properties.get('branch-nick', None))
                    break
            for r in reversed(pending):
                emit_commit(r, branch, git_branch=new_git_branch)

            stream += 'merge :%d\n' % (REVID_TO_MARK[revobj.parent_ids[1]],)
    else:
        parent = bzrlib.revision.NULL_REVISION

    sys.stdout.write(stream.encode('utf-8'))

    ##

    tree_old = branch.repository.revision_tree(parent)
    tree_new = branch.repository.revision_tree(revobj.revision_id)
    changes = tree_new.changes_from(tree_old)

    # make "modified" have 3-tuples, as added does
    my_modified = [ x[0:3] for x in changes.modified ]

    for (oldpath, newpath, id_, kind,
            text_modified, meta_modified) in changes.renamed:
        sys.stdout.write('R %s %s\n' % (my_quote(oldpath, True),
                                                my_quote(newpath)))
        if text_modified or meta_modified:
            my_modified.append((newpath, id_, kind))

    for path, id_, kind in changes.removed:
        sys.stdout.write('D %s\n' % (my_quote(path),))

    for path, id_, kind1, kind2 in changes.kind_changed:
        sys.stdout.write('D %s\n' % (my_quote(path),))
        my_modified.append((path, id_, kind2))

    for path, id_, kind in changes.added + my_modified:
        if kind in ('file', 'symlink'):
            entry = tree_new.inventory[id_]
            if kind == 'file':
                mode = entry.executable and '755' or '644'
                text = tree_new.get_file_text(id_)
            else: # symlink
                mode = '120000'
                text = entry.symlink_target
        else:
            continue

        sys.stdout.write('M %s inline %s\n' % (mode, my_quote(path)))
        sys.stdout.write('data %d\n%s\n' % (len(text), text))

def emit_tags(branch):
    for tag, revid in branch.tags.get_tag_dict().items():
        try:
            mark = REVID_TO_MARK[revid]
        except KeyError:
            print >>sys.stderr, \
                'W: not creating tag %r pointing to non-existant revision %s' % (
                        tag, revid)
        else:
            # According to git-fast-import(1), the extra LF is optional here;
            # however, versions of git up to 1.5.4.3 had a bug by which the LF
            # was needed. Always emit it, since it doesn't hurt and maintains
            # compatibility with older versions.
            # http://git.kernel.org/?p=git/git.git;a=commit;h=655e8515f279c01f525745d443f509f97cd805ab
            sys.stdout.write('reset refs/tags/%s\nfrom :%d\n\n' % (
                tag, mark))

##

def my_quote(string, quote_spaces=False):
    """Encode path in UTF-8 and quote it if necessary.

    A quote is needed if path starts with a quote character ("). If
    :param quote_spaces: is True, the path will be quoted if it contains any
    space (' ') characters.
    """
    # TODO: escape LF
    string = string.encode('utf-8')
    if string.startswith('"') or quote_spaces and ' ' in string:
        return '"%s"%s' % (quote(string),
                GIT_FAST_IMPORT_NEEDS_EXTRA_SPACE_AFTER_QUOTE and ' ' or '')
    else:
        return string

def name_with_angle_brackets(string):
    """Ensure there is a part with angle brackets in string."""
    name, email = parseaddr(string)
    if not name:
        if '@' in email or '<' in string:
            return '<%s>' % (email,)
        else:
            return '%s <>' % (string,)
    else:
        return '%s <%s>' % (name, email)

def next_available_branch_name(prefix=None):
    """Return an unique branch name.

    The returned name will start with :param prefix:, with an extra integer if
    needed for uniqueness.

    If prefix is None, the name will start with "tmp".
    """
    if prefix is None:
        prefix = 'tmp'

    if prefix not in _branch_names:
        _branch_names[prefix] = 0
    else:
        _branch_names[prefix] += 1
        prefix = '%s.%d' % (prefix, _branch_names[prefix])

    return prefix

_branch_names = {}

##

def export_marks(filename, branch_names_dict, revid_to_mark_dict):
    f = file(filename, 'w')
    f.write('format=1\n')

    branch_names = [ '%s.%d' % x for x in branch_names_dict.iteritems() ]
    f.write('\0'.join(branch_names) + '\n')

    for mark, revid in sorted((y, x)
            for x, y in revid_to_mark_dict.iteritems()):
        f.write(':%d %s\n' % (mark, revid))

    f.close()

def import_marks(filename):
    f = file(filename)
    firstline = f.readline()
    match = re.match(r'^format=(\d+)$', firstline)

    if not match:
        print >>sys.stderr, "%r doesn't look like a mark file" % (filename,)
        sys.exit(1)
    elif match.group(1) != '1':
        print >>sys.stderr, 'format version in mark file not supported'
        sys.exit(1)

    branch_names = {}

    for string in f.readline().rstrip('\n').split('\0'):
        if not string:
            continue
        name, integer = string.rsplit('.', 1)
        branch_names[name] = int(integer)

    revid_to_mark = {}

    for line in f:
        line = line.rstrip('\n')
        mark, revid = line.split(' ', 1)
        mark = mark[1:] # strip colon
        revid_to_mark[revid] = int(mark)

    return branch_names, revid_to_mark

##

def parse_options():
    p = optparse.OptionParser(usage='%prog [options] BZR_BRANCH')

    p.add_option('-b', '--git-branch', default='master', metavar='NAME',
            help='name of the git branch to create (default: master)')

    p.add_option('--export-marks', metavar='FILE',
            help='export marks to FILE, useful to import further related branches')

    p.add_option('--import-marks', metavar='FILE',
            help='import a mark file previously created with --export-marks')

    options, args = p.parse_args()

    if len(args) != 1:
        p.error('need a branch to export')

    return options, args

##

if __name__ == '__main__':
    sys.exit(main())
