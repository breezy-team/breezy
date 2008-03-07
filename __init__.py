"""A Simple bzr plugin to generate statistics about the history."""

import re

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    branch,
    commands,
    config,
    errors,
    tsort,
    ui,
    workingtree,
    )
""")
from bzrlib import lazy_regex


_fullname_re = lazy_regex.lazy_compile(r'(?P<fullname>.*?)\s*<')

def extract_fullname(committer):
    """Try to get the user's name from their committer info."""
    m = _fullname_re.match(committer)
    if m:
        return m.group('fullname')
    try:
        email = config.extract_email_address(committer)
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


def sort_by_committer(a_repo, revids):
    committers = {}
    pb = ui.ui_factory.nested_progress_bar()
    try:
        pb.note('getting revisions')
        revisions = a_repo.get_revisions(revids)
        for count, rev in enumerate(revisions):
            pb.update('checking', count, len(revids))
            try:
                email = config.extract_email_address(rev.committer)
            except errors.BzrError:
                email = rev.committer
            committers.setdefault(email, []).append(rev)
    finally:
        pb.finished()
    
    return committers


def get_info(a_repo, revision):
    """Get all of the information for a particular revision"""
    pb = ui.ui_factory.nested_progress_bar()
    a_repo.lock_read()
    try:
        pb.note('getting ancestry')
        ancestry = a_repo.get_ancestry(revision)[1:]

        committers = sort_by_committer(a_repo, ancestry)
    finally:
        a_repo.unlock()
        pb.finished()

    return collapse_by_author(committers)


def get_diff_info(a_repo, start_rev, end_rev):
    """Get only the info for new revisions between the two revisions
    
    This lets us figure out what has actually changed between 2 revisions.
    """
    pb = ui.ui_factory.nested_progress_bar()
    committers = {}
    a_repo.lock_read()
    try:
        pb.note('getting ancestry 1')
        start_ancestry = set(a_repo.get_ancestry(start_rev))
        pb.note('getting ancestry 2')
        ancestry = a_repo.get_ancestry(end_rev)[1:]
        ancestry = [rev for rev in ancestry if rev not in start_ancestry]
        pb.note('getting revisions')
        revisions = a_repo.get_revisions(ancestry)

        for count, rev in enumerate(revisions):
            pb.update('checking', count, len(ancestry))
            try:
                email = config.extract_email_address(rev.committer)
            except errors.BzrError:
                email = rev.committer
            committers.setdefault(email, []).append(rev)
    finally:
        a_repo.unlock()
        pb.finished()

    info = collapse_by_author(committers)
    return info

def display_info(info, to_file):
    """Write out the information"""

    for count, revs, emails, fullnames in info:
        # Get the most common email name
        sorted_emails = sorted(((count, email)
                               for email,count in emails.iteritems()),
                               reverse=True)
        sorted_fullnames = sorted(((count, fullname)
                                  for fullname,count in fullnames.iteritems()),
                                  reverse=True)
        to_file.write('%4d %s <%s>\n'
                      % (count, sorted_fullnames[0][1],
                         sorted_emails[0][1]))
        if len(sorted_fullnames) > 1:
            print '     Other names:'
            for count, fname in sorted_fullnames[1:]:
                to_file.write('     %4d ' % (count,))
                if fname == '':
                    to_file.write("''\n")
                else:
                    to_file.write("%s\n" % (fname,))
        if len(sorted_emails) > 1:
            print '     Other email addresses:'
            for count, email in sorted_emails:
                to_file.write('     %4d ' % (count,))
                if email == '':
                    to_file.write("''\n")
                else:
                    to_file.write("%s\n" % (email,))


class cmd_statistics(commands.Command):
    """Generate statistics for LOCATION."""

    aliases = ['stats']
    takes_args = ['location?']
    takes_options = ['revision']

    encoding_type = 'replace'

    def run(self, location='.', revision=None):
        alternate_rev = None
        try:
            wt = workingtree.WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            a_branch = branch.Branch.open(location)
            last_rev = a_branch.last_revision()
        else:
            a_branch = wt.branch
            last_rev = wt.last_revision()

        if revision is not None:
            last_rev = revision[0].in_history(a_branch).rev_id
            if len(revision) > 1:
                alternate_rev = revision[1].in_history(a_branch).rev_id

        a_branch.lock_read()
        try:
            if alternate_rev:
                info = get_diff_info(a_branch.repository, last_rev,
                                     alternate_rev)
            else:
                info = get_info(a_branch.repository, last_rev)
        finally:
            a_branch.unlock()
        display_info(info, self.outf)


commands.register_command(cmd_statistics)


class cmd_ancestor_growth(commands.Command):
    """Figure out the ancestor graph for LOCATION"""

    takes_args = ['location?']

    encoding_type = 'replace'

    def run(self, location='.'):
        try:
            wt = workingtree.WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            a_branch = branch.Branch.open(location)
            last_rev = a_branch.last_revision()
        else:
            a_branch = wt.branch
            last_rev = wt.last_revision()

        a_branch.lock_read()
        try:
            graph = a_branch.repository.get_revision_graph(last_rev)
        finally:
            a_branch.unlock()

        revno = 0
        cur_parents = 0
        sorted_graph = tsort.merge_sort(graph.iteritems(), last_rev)
        for num, node_name, depth, isend in reversed(sorted_graph):
            cur_parents += 1
            if depth == 0:
                revno += 1
                self.outf.write('%4d, %4d\n' % (revno, cur_parents))


commands.register_command(cmd_ancestor_growth)


def test_suite():
    from unittest import TestSuite
    from bzrlib.tests import TestLoader
    import test_stats
    suite = TestSuite()
    loader = TestLoader()
    testmod_names = ['test_stats']
    suite.addTest(loader.loadTestsFromModuleNames(['%s.%s' % (__name__, i) for i in testmod_names]))
    return suite

