"""A Simple bzr plugin to generate statistics about the history."""

import re

from bzrlib import errors, tsort
from bzrlib.branch import Branch
import bzrlib.commands
from bzrlib.config import extract_email_address
from bzrlib.workingtree import WorkingTree


_fullname_re = re.compile(r'(?P<fullname>.*?)\s*<')

def extract_fullname(committer):
    """Try to get the user's name from their committer info."""
    m = _fullname_re.match(committer)
    if m:
        return m.group('fullname')
    try:
        email = extract_email_address(committer)
    except errors.BzrError:
        return committer
    else:
        # We found an email address, but not a fullname
        # so there is no fullname
        return ''


def find_fullnames(lst):
    """Find the fullnames for a list committer names."""

    counts = {}
    for committer in lst:
        fullname = extract_fullname(committer)
        counts.setdefault(fullname, 0)
        counts[fullname] += 1
    return sorted(((count, name) for name,count in counts.iteritems()), reverse=True)


def collapse_by_author(committers):
    """The committers list is sorted by email, fix it up by author.

    Some people commit with a similar username, but different email
    address. Which makes it hard to sort out when they have multiple
    entries. Email is actually more stable, though, since people
    frequently forget to set their name properly.

    So take the most common username for each email address, and
    combine them into one new list.
    """
    # Just an indirection so that multiple names can reference
    # the same record information
    name_to_counter = {}
    # indirection back to real information
    # [[full_rev_list], {email:count}, {fname:count}]
    counter_to_info = {}
    counter = 0
    for email, revs in committers.iteritems():
        fullnames = find_fullnames(rev.committer for rev in revs)
        match = None
        for count, fullname in fullnames:
            if fullname and fullname in name_to_counter:
                # We found a match
                match = name_to_counter[fullname]
                break

        if match:
            # One of the names matched, we need to collapse to records
            record = counter_to_info[match]
            record[0].extend(revs)
            record[1][email] = len(revs)
            for count, fullname in fullnames:
                name_to_counter[fullname] = match
                record[2].setdefault(fullname, 0)
                record[2][fullname] += count
        else:
            # just add this one to the list
            counter += 1
            for count, fullname in fullnames:
                if fullname:
                    name_to_counter[fullname] = counter
            fname_map = dict((fullname, count) for count, fullname in fullnames)
            counter_to_info[counter] = [revs, {email:len(revs)}, fname_map]
    return sorted(((len(revs), revs, email, fname) 
            for revs, email, fname in counter_to_info.values()), reverse=True)


class cmd_statistics(bzrlib.commands.Command):
    """Generate statistics for LOCATION."""

    aliases = ['stats']
    takes_args = ['location?']

    encoding_type = 'replace'

    def run(self, location='.'):
        try:
            wt = WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            b = Branch.open(location)
            last_rev = b.last_revision()
        else:
            b = wt.branch
            last_rev = wt.last_revision()

        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        committers = {}
        b.lock_read()
        try:
            pb.note('getting ancestry')
            ancestry = b.repository.get_ancestry(last_rev)[1:]
            pb.note('getting revisions')
            revisions = b.repository.get_revisions(ancestry)

            for count, rev in enumerate(revisions):
                pb.update('checking', count, len(ancestry))
                try:
                    email = extract_email_address(rev.committer)
                except errors.BzrError:
                    email = rev.committer
                committers.setdefault(email, []).append(rev)
        finally:
            b.unlock()
        pb.clear()

        info = collapse_by_author(committers)
        for count, revs, emails, fullnames in info:
            # Get the most common email name
            sorted_emails = sorted(((count, email) 
                                   for email,count in emails.iteritems()),
                                   reverse=True)
            sorted_fullnames = sorted(((count, fullname) 
                                      for fullname,count in fullnames.iteritems()),
                                      reverse=True)
            self.outf.write('%4d %s <%s>\n' 
                            % (count, sorted_fullnames[0][1],
                               sorted_emails[0][1]))
            if len(sorted_fullnames) > 1:
                print '     Other names:'
                for count, fname in sorted_fullnames[1:]:
                    self.outf.write('     %4d ' % (count,))
                    if fname == '':
                        self.outf.write("''\n")
                    else:
                        self.outf.write("%s\n" % (fname,))
            if len(sorted_emails) > 1:
                print '     Other email addresses:'
                for count, email in sorted_emails:
                    self.outf.write('     %4d ' % (count,))
                    if email == '':
                        self.outf.write("''\n")
                    else:
                        self.outf.write("%s\n" % (email,))


bzrlib.commands.register_command(cmd_statistics)


class cmd_ancestor_growth(bzrlib.commands.Command):
    """Figure out the ancestor graph for LOCATION"""

    takes_args = ['location?']

    encoding_type = 'replace'

    def run(self, location='.'):
        try:
            wt = WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            b = Branch.open(location)
            last_rev = b.last_revision()
        else:
            b = wt.branch
            last_rev = wt.last_revision()

        b.lock_read()
        try:
            graph = b.repository.get_revision_graph(last_rev)
        finally:
            b.unlock()

        revno = 0
        cur_parents = 0
        sorted_graph = tsort.merge_sort(graph.iteritems(), last_rev)
        for num, node_name, depth, isend in reversed(sorted_graph):
            cur_parents += 1
            if depth == 0:
                revno += 1
                self.outf.write('%4d, %4d\n' % (revno, cur_parents))


bzrlib.commands.register_command(cmd_ancestor_growth)
