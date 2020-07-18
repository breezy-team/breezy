# Copyright (C) 2006-2010 Canonical Ltd

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

import operator

from ... import (
    branch,
    commands,
    config,
    errors,
    option,
    trace,
    tsort,
    ui,
    workingtree,
    )
from ...revision import NULL_REVISION
from .classify import classify_delta


def collapse_by_person(revisions, canonical_committer):
    """The committers list is sorted by email, fix it up by person.

    Some people commit with a similar username, but different email
    address. Which makes it hard to sort out when they have multiple
    entries. Email is actually more stable, though, since people
    frequently forget to set their name properly.

    So take the most common username for each email address, and
    combine them into one new list.
    """
    # Map from canonical committer to
    # {committer: ([rev_list], {email: count}, {fname:count})}
    committer_to_info = {}
    for rev in revisions:
        authors = rev.get_apparent_authors()
        for author in authors:
            username, email = config.parse_username(author)
            if len(username) == 0 and len(email) == 0:
                continue
            canon_author = canonical_committer[(username, email)]
            info = committer_to_info.setdefault(canon_author, ([], {}, {}))
            info[0].append(rev)
            info[1][email] = info[1].setdefault(email, 0) + 1
            info[2][username] = info[2].setdefault(username, 0) + 1
    res = [(len(revs), revs, emails, fnames)
           for revs, emails, fnames in committer_to_info.values()]

    def key_fn(item):
        return item[0], list(item[2].keys())
    res.sort(reverse=True, key=key_fn)
    return res


def collapse_email_and_users(email_users, combo_count):
    """Combine the mapping of User Name to email and email to User Name.

    If a given User Name is used for multiple emails, try to map it all to one
    entry.
    """
    id_to_combos = {}
    username_to_id = {}
    email_to_id = {}
    id_counter = 0

    def collapse_ids(old_id, new_id, new_combos):
        old_combos = id_to_combos.pop(old_id)
        new_combos.update(old_combos)
        for old_user, old_email in old_combos:
            if (old_user and old_user != user):
                low_old_user = old_user.lower()
                old_user_id = username_to_id[low_old_user]
                assert old_user_id in (old_id, new_id)
                username_to_id[low_old_user] = new_id
            if (old_email and old_email != email):
                old_email_id = email_to_id[old_email]
                assert old_email_id in (old_id, new_id)
                email_to_id[old_email] = cur_id
    for email, usernames in email_users.items():
        assert email not in email_to_id
        if not email:
            # We use a different algorithm for usernames that have no email
            # address, we just try to match by username, and not at all by
            # email
            for user in usernames:
                if not user:
                    continue  # The mysterious ('', '') user
                # When mapping, use case-insensitive names
                low_user = user.lower()
                user_id = username_to_id.get(low_user)
                if user_id is None:
                    id_counter += 1
                    user_id = id_counter
                    username_to_id[low_user] = user_id
                    id_to_combos[user_id] = id_combos = set()
                else:
                    id_combos = id_to_combos[user_id]
                id_combos.add((user, email))
            continue

        id_counter += 1
        cur_id = id_counter
        id_to_combos[cur_id] = id_combos = set()
        email_to_id[email] = cur_id

        for user in usernames:
            combo = (user, email)
            id_combos.add(combo)
            if not user:
                # We don't match on empty usernames
                continue
            low_user = user.lower()
            user_id = username_to_id.get(low_user)
            if user_id is not None:
                # This UserName was matched to an cur_id
                if user_id != cur_id:
                    # And it is a different identity than the current email
                    collapse_ids(user_id, cur_id, id_combos)
            username_to_id[low_user] = cur_id
    combo_to_best_combo = {}
    for cur_id, combos in id_to_combos.items():
        best_combo = sorted(combos,
                            key=lambda x: combo_count[x],
                            reverse=True)[0]
        for combo in combos:
            combo_to_best_combo[combo] = best_combo
    return combo_to_best_combo


def get_revisions_and_committers(a_repo, revids):
    """Get the Revision information, and the best-match for committer."""

    email_users = {}  # user@email.com => User Name
    combo_count = {}
    with ui.ui_factory.nested_progress_bar() as pb:
        trace.note('getting revisions')
        revisions = list(a_repo.iter_revisions(revids))
        for count, (revid, rev) in enumerate(revisions):
            pb.update('checking', count, len(revids))
            for author in rev.get_apparent_authors():
                # XXX: There is a chance sometimes with svn imports that the
                #      full name and email can BOTH be blank.
                username, email = config.parse_username(author)
                email_users.setdefault(email, set()).add(username)
                combo = (username, email)
                combo_count[combo] = combo_count.setdefault(combo, 0) + 1
    return ((rev for (revid, rev) in revisions),
            collapse_email_and_users(email_users, combo_count))


def get_info(a_repo, revision):
    """Get all of the information for a particular revision"""
    with ui.ui_factory.nested_progress_bar() as pb, a_repo.lock_read():
        trace.note('getting ancestry')
        graph = a_repo.get_graph()
        ancestry = [
            r for (r, ps) in graph.iter_ancestry([revision])
            if ps is not None and r != NULL_REVISION]
        revs, canonical_committer = get_revisions_and_committers(
            a_repo, ancestry)

    return collapse_by_person(revs, canonical_committer)


def get_diff_info(a_repo, start_rev, end_rev):
    """Get only the info for new revisions between the two revisions

    This lets us figure out what has actually changed between 2 revisions.
    """
    with ui.ui_factory.nested_progress_bar() as pb, a_repo.lock_read():
        graph = a_repo.get_graph()
        trace.note('getting ancestry diff')
        ancestry = graph.find_difference(start_rev, end_rev)[1]
        revs, canonical_committer = get_revisions_and_committers(
            a_repo, ancestry)

    return collapse_by_person(revs, canonical_committer)


def display_info(info, to_file, gather_class_stats=None):
    """Write out the information"""

    for count, revs, emails, fullnames in info:
        # Get the most common email name
        sorted_emails = sorted(((count, email)
                                for email, count in emails.items()),
                               reverse=True)
        sorted_fullnames = sorted(((count, fullname)
                                   for fullname, count in fullnames.items()),
                                  reverse=True)
        if sorted_fullnames[0][1] == '' and sorted_emails[0][1] == '':
            to_file.write('%4d %s\n'
                          % (count, 'Unknown'))
        else:
            to_file.write('%4d %s <%s>\n'
                          % (count, sorted_fullnames[0][1],
                             sorted_emails[0][1]))
        if len(sorted_fullnames) > 1:
            to_file.write('     Other names:\n')
            for count, fname in sorted_fullnames:
                to_file.write('     %4d ' % (count,))
                if fname == '':
                    to_file.write("''\n")
                else:
                    to_file.write("%s\n" % (fname,))
        if len(sorted_emails) > 1:
            to_file.write('     Other email addresses:\n')
            for count, email in sorted_emails:
                to_file.write('     %4d ' % (count,))
                if email == '':
                    to_file.write("''\n")
                else:
                    to_file.write("%s\n" % (email,))
        if gather_class_stats is not None:
            to_file.write('     Contributions:\n')
            classes, total = gather_class_stats(revs)
            for name, count in sorted(classes.items(), key=classify_key):
                if name is None:
                    name = "Unknown"
                to_file.write("     %4.0f%% %s\n" %
                              ((float(count) / total) * 100.0, name))


class cmd_committer_statistics(commands.Command):
    """Generate statistics for LOCATION."""

    aliases = ['stats', 'committer-stats']
    takes_args = ['location?']
    takes_options = ['revision',
                     option.Option('show-class', help="Show the class of contributions.")]

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

        with a_branch.lock_read():
            if alternate_rev:
                info = get_diff_info(a_branch.repository, last_rev,
                                     alternate_rev)
            else:
                info = get_info(a_branch.repository, last_rev)
        if show_class:
            def fetch_class_stats(revs):
                return gather_class_stats(a_branch.repository, revs)
        else:
            fetch_class_stats = None
        display_info(info, self.outf, fetch_class_stats)


class cmd_ancestor_growth(commands.Command):
    """Figure out the ancestor graph for LOCATION"""

    takes_args = ['location?']

    encoding_type = 'replace'

    hidden = True

    def run(self, location='.'):
        try:
            wt = workingtree.WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            a_branch = branch.Branch.open(location)
            last_rev = a_branch.last_revision()
        else:
            a_branch = wt.branch
            last_rev = wt.last_revision()

        with a_branch.lock_read():
            graph = a_branch.repository.get_graph()
            revno = 0
            cur_parents = 0
            sorted_graph = tsort.merge_sort(graph.iter_ancestry([last_rev]),
                                            last_rev)
            for num, node_name, depth, isend in reversed(sorted_graph):
                cur_parents += 1
                if depth == 0:
                    revno += 1
                    self.outf.write('%4d, %4d\n' % (revno, cur_parents))


def gather_class_stats(repository, revs):
    ret = {}
    total = 0
    with ui.ui_factory.nested_progress_bar() as pb:
        with repository.lock_read():
            i = 0
            for delta in repository.get_revision_deltas(revs):
                pb.update("classifying commits", i, len(revs))
                for c in classify_delta(delta):
                    if c not in ret:
                        ret[c] = 0
                    ret[c] += 1
                    total += 1
                i += 1
    return ret, total


def classify_key(item):
    """Sort key for item of (author, count) from classify_delta."""
    return -item[1], item[0]


def display_credits(credits, to_file):
    (coders, documenters, artists, translators) = credits

    def print_section(name, lst):
        if len(lst) == 0:
            return
        to_file.write("%s:\n" % name)
        for name in lst:
            to_file.write("%s\n" % name)
        to_file.write('\n')
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
    with repository.lock_read():
        graph = repository.get_graph()
        ancestry = [r for (r, ps) in graph.iter_ancestry([revid])
                    if ps is not None and r != NULL_REVISION]
        revs = repository.get_revisions(ancestry)
        with ui.ui_factory.nested_progress_bar() as pb:
            iterator = zip(revs, repository.get_revision_deltas(revs))
            for i, (rev, delta) in enumerate(iterator):
                pb.update("analysing revisions", i, len(revs))
                # Don't count merges
                if len(rev.parent_ids) > 1:
                    continue
                for c in set(classify_delta(delta)):
                    for author in rev.get_apparent_authors():
                        if author not in ret[c]:
                            ret[c][author] = 0
                        ret[c][author] += 1

    def sort_class(name):
        return [author
                for author, _ in sorted(ret[name].items(), key=classify_key)]
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

        with a_branch.lock_read():
            credits = find_credits(a_branch.repository, last_rev)
            display_credits(credits, self.outf)
