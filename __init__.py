# Copyright (C) 2005-2008 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""A Simple bzr plugin to generate statistics about the history."""

import re

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    branch,
    commands,
    config,
    errors,
    option,
    tsort,
    ui,
    workingtree,
    )
from bzrlib.plugins.stats.classify import classify_delta
from itertools import izip
""")


def find_fullnames(lst):
    """Find the fullnames for a list committer names."""

    counts = {}
    for committer in lst:
        fullname = config.parse_username(committer)[0]
        counts.setdefault(fullname, 0)
        counts[fullname] += 1
    return sorted(((count, name) for name,count in counts.iteritems()),
        reverse=True)


def collapse_by_person(committers):
    """The committers list is sorted by email, fix it up by person.

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
        authors = []
        for rev in revs:
            authors += rev.get_apparent_authors()
        fullnames = find_fullnames(authors)
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
            for author in rev.get_apparent_authors():
                username = config.parse_username(author)
                if username[1] == '':
                    email = username[0]
                else:
                    email = username[1]
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

    return collapse_by_person(committers)


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
            for author in rev.get_apparent_authors():
                try:
                    email = config.extract_email_address(author)
                except errors.BzrError:
                    email = author
                committers.setdefault(email, []).append(rev)
    finally:
        a_repo.unlock()
        pb.finished()

    info = collapse_by_person(committers)
    return info


def display_info(info, to_file, gather_class_stats=None):
    """Write out the information"""

    for count, revs, emails, fullnames in info:
        # Get the most common email name
        sorted_emails = sorted(((count, email)
                               for email,count in emails.iteritems()),
                               reverse=True)
        sorted_fullnames = sorted(((count, fullname)
                                  for fullname,count in fullnames.iteritems()),
                                  reverse=True)
        # There is a chance sometimes with svn imports that the full name and
        # email can BOTH be blank.
        if sorted_fullnames[0][1] == '':
            to_file.write('%4d %s\n'
                          % (count, 'Unknown'))
        else:
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
        if gather_class_stats is not None:
            print '     Contributions:'
            classes, total = gather_class_stats(revs)
            for name,count in sorted(classes.items(), lambda x,y: cmp((x[1], x[0]), (y[1], y[0]))):
                if name is None:
                    name = "Unknown"
                to_file.write("     %4.0f%% %s\n" % ((float(count) / total) * 100.0, name))


class cmd_committer_statistics(commands.Command):
    """Generate statistics for LOCATION."""

    aliases = ['stats', 'committer-stats']
    takes_args = ['location?']
    takes_options = ['revision', 
            option.Option('show-class', help="Show the class of contributions")]

    encoding_type = 'replace'

    def run(self, location='.', revision=None, show_class=False):
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
        if show_class:
            def fetch_class_stats(revs):
                return gather_class_stats(a_branch.repository, revs)
        else:
            fetch_class_stats = None
        display_info(info, self.outf, fetch_class_stats)


commands.register_command(cmd_committer_statistics)


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


def gather_class_stats(repository, revs):
    ret = {}
    total = 0
    pb = ui.ui_factory.nested_progress_bar()
    try:
        repository.lock_read()
        try:
            i = 0
            for delta in repository.get_deltas_for_revisions(revs):
                pb.update("classifying commits", i, len(revs))
                for c in classify_delta(delta):
                    if not c in ret:
                        ret[c] = 0
                    ret[c] += 1
                    total += 1
                i += 1
        finally:
            repository.unlock()
    finally:
        pb.finished()
    return ret, total


def display_credits(credits):
    (coders, documenters, artists, translators) = credits
    def print_section(name, lst):
        if len(lst) == 0:
            return
        print "%s:" % name
        for name in lst:
            print "%s" % name
        print ""
    print_section("Code", coders)
    print_section("Documentation", documenters)
    print_section("Art", artists)
    print_section("Translations", translators)


def find_credits(repository, revid):
    """Find the credits of the contributors to a revision.

    :return: tuple with (authors, documenters, artists, translators)
    """
    ret = {"documentation": {},
           "code": {},
           "art": {},
           "translation": {},
           None: {}
           }
    repository.lock_read()
    try:
        ancestry = filter(lambda x: x is not None, repository.get_ancestry(revid))
        revs = repository.get_revisions(ancestry)
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for i, (rev,delta) in enumerate(izip(revs, repository.get_deltas_for_revisions(revs))):
                pb.update("analysing revisions", i, len(revs))
                # Don't count merges
                if len(rev.parent_ids) > 1:
                    continue
                for c in set(classify_delta(delta)):
                    for author in rev.get_apparent_authors():
                        if not author in ret[c]:
                            ret[c][author] = 0
                        ret[c][author] += 1
        finally:
            pb.finished()
    finally:
        repository.unlock()
    def sort_class(name):
        return map(lambda (x,y): x, 
               sorted(ret[name].items(), lambda x,y: cmp((x[1], x[0]), (y[1], y[0])), reverse=True))
    return (sort_class("code"), sort_class("documentation"), sort_class("art"), sort_class("translation"))


class cmd_credits(commands.Command):
    """Determine credits for LOCATION."""

    takes_args = ['location?']
    takes_options = ['revision']

    encoding_type = 'replace'

    def run(self, location='.', revision=None):
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

        a_branch.lock_read()
        try:
            credits = find_credits(a_branch.repository, last_rev)
            display_credits(credits)
        finally:
            a_branch.unlock()


commands.register_command(cmd_credits)


def test_suite():
    from unittest import TestSuite
    from bzrlib.tests import TestLoader
    suite = TestSuite()
    loader = TestLoader()
    testmod_names = [ 'test_classify']
    suite.addTest(loader.loadTestsFromModuleNames(['%s.%s' % (__name__, i) for i in testmod_names]))
    return suite

