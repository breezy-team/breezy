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
from bzrlib import errors as bazErrors

class BzrFastExporter:

    def __init__(self, options):
        self.options = options
        self.revid_to_mark = {}
        self.branch_names = {}
        
        if options.marks:                                              
            options.import_marks = options.export_marks = options.marks
        
        if options.import_marks:
            self.import_marks()
        
        if options.checkpoint:
            self.checkpoint = int(options.checkpoint)
        else:
            self.checkpoint = -1
        
        self.branch = bzrlib.branch.Branch.open_containing(options.repo)[0]
        self.branch.repository.lock_read()
        self.revmap = self.branch.get_revision_id_to_revno_map()
            
    def run(self):
        try:
            for revid in self.branch.revision_history():
                if revid not in self.revid_to_mark:
                    self.emit_commit(revid, options.git_branch)
        finally:
            self.branch.repository.unlock()

        if self.branch.supports_tags():
            self.emit_tags()

        ##
        self.export_marks()

    def debug(self, message):
        sys.stderr.write("*** BzrFastExport: %s\n" % message)
            
    def emit_commit(self, revid, git_branch):
        if revid in self.revid_to_mark:
            return

        try:
            revobj = self.branch.repository.get_revision(revid)
        except bazErrors.NoSuchRevision:
            # This is a ghost revision. Mark it as not found and next!
            self.revid_to_mark[revid] = -1
            return

        
        ncommits = len(self.revid_to_mark)
        if self.checkpoint > 0 and ncommits % self.checkpoint == 0:
            self.debug(
                "Exported %i commits; forcing checkpoint" % ncommits)
            self.export_marks()
            sys.stdout.write("checkpoint\n")

        mark = self.revid_to_mark[revid] = len(self.revid_to_mark) + 1
        nparents = len(revobj.parent_ids)

        # This is a parentless commit. We need to create a new branch
        # otherwise git-fast-import will assume the previous commit
        # was this one's parent
        for parent in revobj.parent_ids:
            self.emit_commit(parent, git_branch)

        if nparents == 0:
            git_branch = self.next_available_branch_name()
            parent = bzrlib.revision.NULL_REVISION
        else:
            parent = revobj.parent_ids[0]
        

        stream = 'commit refs/heads/%s\nmark :%d\n' % (git_branch, mark)

        rawdate = '%d %s' % (int(revobj.timestamp), '%+03d%02d' % (
                    revobj.timezone / 3600, (revobj.timezone / 60) % 60))

        author = revobj.get_apparent_author()
        if author != revobj.committer:
            stream += 'author %s %s\n' % (
                self.name_with_angle_brackets(author), rawdate)

        stream += 'committer %s %s\n' % (
                self.name_with_angle_brackets(revobj.committer), rawdate)

        message = revobj.message.encode('utf-8')
        stream += 'data %d\n%s\n' % (len(message), revobj.message)

        didFirstParent = False
        for p in revobj.parent_ids:
            if self.revid_to_mark[p] == -1:
                self.debug("This is a merge with a ghost-commit. Skipping second parent.")
                continue

            if p == parent and not didFirstParent:
                s = "from"
                didFirstParent = True
            else:
                s = "merge"
            stream += '%s :%d\n' % (s, self.revid_to_mark[p])


        sys.stdout.write(stream.encode('utf-8'))

        ##

        try:
            tree_old = self.branch.repository.revision_tree(parent)
        except bazErrors.UnexpectedInventoryFormat:
            self.debug("Parent is malformed.. diffing against previous parent")
            # We can't find the old parent. Let's diff against his parent
            pp = self.branch.repository.get_revision(parent)
            tree_old = self.branch.repository.revision_tree(pp.parent_ids[0])
        
        tree_new = None
        try:
            tree_new = self.branch.repository.revision_tree(revobj.revision_id)
        except bazErrors.UnexpectedInventoryFormat:
            # We can't really do anything anymore
            self.debug("This commit is malformed. Skipping diff")
            return

        changes = tree_new.changes_from(tree_old)

        # make "modified" have 3-tuples, as added does
        my_modified = [ x[0:3] for x in changes.modified ]

        # We have to keep track of previous renames in this commit
        renamed = {}
        for (oldpath, newpath, id_, kind,
                text_modified, meta_modified) in changes.renamed:
            for old, new in renamed.iteritems():
                # If a previous rename is found in this rename, we should
                # adjust the path
                if re.match(old, oldpath):
                    oldpath = re.sub(old + "/", new + "/", oldpath) 
                    self.debug("Fixing recursive rename for %s" % oldpath)

            renamed[oldpath] = newpath

            sys.stdout.write('R %s %s\n' % (self.my_quote(oldpath, True),
                                                    self.my_quote(newpath)))
            if text_modified or meta_modified:
                my_modified.append((newpath, id_, kind))

        for path, id_, kind in changes.removed:
            sys.stdout.write('D %s\n' % (self.my_quote(path),))

        for path, id_, kind1, kind2 in changes.kind_changed:
            sys.stdout.write('D %s\n' % (self.my_quote(path),))
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

            sys.stdout.write('M %s inline %s\n' % (mode, self.my_quote(path)))
            sys.stdout.write('data %d\n%s\n' % (len(text), text))

    def emit_tags(self):
        for tag, revid in self.branch.tags.get_tag_dict().items():
            try:
                mark = self.revid_to_mark[revid]
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

    def my_quote(self, string, quote_spaces=False):
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

    def name_with_angle_brackets(self, string):
        """Ensure there is a part with angle brackets in string."""
        name, email = parseaddr(string)
        if not name:
            if '@' in email or '<' in string:
                return '<%s>' % (email,)
            else:
                return '%s <>' % (string,)
        else:
            return '%s <%s>' % (name, email)

    def next_available_branch_name(self):
        """Return an unique branch name. The name will start with "tmp".
        """
        prefix = 'tmp'

        if prefix not in self.branch_names:
            self.branch_names[prefix] = 0
        else:
            self.branch_names[prefix] += 1
            prefix = '%s.%d' % (prefix, self.branch_names[prefix])

        return prefix

    def export_marks(self):
        if not self.options.export_marks:
            return
            
        f = file(self.options.export_marks, 'w')
        f.write('format=1\n')

        branch_names = [ '%s.%d' % x for x in self.branch_names.iteritems() ]
        f.write('\0'.join(branch_names) + '\n')

        for mark, revid in sorted((y, x)
                for x, y in self.revid_to_mark.iteritems()):
            f.write(':%d %s\n' % (mark, revid))

        f.close()

    def import_marks(self):
        try:
            f = file(options.import_marks)
        except IOError:
            self.debug("Could not open import-marks file, not importing marks")
            return

        firstline = f.readline()
        match = re.match(r'^format=(\d+)$', firstline)

        if not match:
            print >>sys.stderr, "%r doesn't look like a mark file" % (filename,)
            sys.exit(1)
        elif match.group(1) != '1':
            print >>sys.stderr, 'format version in mark file not supported'
            sys.exit(1)



        for string in f.readline().rstrip('\n').split('\0'):
            if not string:
                continue
            name, integer = string.rsplit('.', 1)
            self.branch_names[name] = int(integer)

        for line in f:
            line = line.rstrip('\n')
            mark, revid = line.split(' ', 1)
            mark = mark[1:] # strip colon
            self.revid_to_mark[revid] = int(mark)
##

def parse_options():
    p = optparse.OptionParser(usage='%prog [options] BZR_BRANCH')

    p.add_option('-b', '--git-branch', default='master', metavar='NAME',
            help='name of the git branch to create (default: master)')

    p.add_option('--export-marks', metavar='FILE',
            help='export marks to FILE, useful to import further related branches')

    p.add_option('--import-marks', metavar='FILE',
            help='import a mark file previously created with --export-marks')

    p.add_option("--marks", metavar='FILE',
            help='import marks, and export them to the same file.')

    p.add_option("--checkpoint", metavar="NUM", default=1000,
            help='Checkpoint every N revisions')
    
    options, args = p.parse_args()

    if len(args) != 1:
        p.error('need a branch to export')
    options.repo = args[0]

    return options, args

##

if __name__ == '__main__':
    options, arguments = parse_options()
    exporter = BzrFastExporter(options)
    sys.exit(exporter.run())
