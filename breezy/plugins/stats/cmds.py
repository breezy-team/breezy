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

import vcsgraph.tsort as tsort

from ... import branch, commands, config, errors, option, trace, ui, workingtree
from ...revision import NULL_REVISION
from .classify import classify_delta


def collapse_by_person(revisions, canonical_committer):
    """Collapse revisions by person, combining entries for the same person.

    The committers list is sorted by email, fix it up by person.
    Some people commit with a similar username, but different email
    address. Which makes it hard to sort out when they have multiple
    entries. Email is actually more stable, though, since people
    frequently forget to set their name properly.

    So take the most common username for each email address, and
    combine them into one new list.

    Args:
        revisions: Iterable of revision objects to process.
        canonical_committer: Dictionary mapping (username, email) tuples
            to canonical committer identities.

    Returns:
        List of tuples in format (commit_count, revisions_list, emails_dict,
        fullnames_dict) sorted by commit count in descending order.
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
    res = [
        (len(revs), revs, emails, fnames)
        for revs, emails, fnames in committer_to_info.values()
    ]

    def key_fn(item):
        """Generate sort key for committer statistics items.

        Args:
            item: Tuple of (commit_count, revisions_list, emails_dict, fullnames_dict).

        Returns:
            Tuple for sorting by commit count and then by fullname keys.
        """
        return item[0], list(item[2].keys())

    res.sort(reverse=True, key=key_fn)
    return res


def collapse_email_and_users(email_users, combo_count):
    """Combine mappings of usernames to emails and emails to usernames.

    If a given User Name is used for multiple emails, try to map it all to one
    entry. This function resolves identity conflicts by creating canonical
    mappings for each unique person based on both username and email patterns.

    Args:
        email_users: Dictionary mapping email addresses to sets of usernames
            that have used that email.
        combo_count: Dictionary mapping (username, email) tuples to their
            occurrence counts.

    Returns:
        Dictionary mapping (username, email) tuples to their canonical
        (username, email) representation.
    """
    id_to_combos = {}
    username_to_id = {}
    email_to_id = {}
    id_counter = 0

    def collapse_ids(old_id, new_id, new_combos):
        """Collapse two identity IDs into one, updating all mappings.

        Merges the identity represented by old_id into new_id, updating
        all internal mappings to maintain consistency.

        Args:
            old_id: Identity ID to be collapsed.
            new_id: Target identity ID to merge into.
            new_combos: Set of (username, email) combos for the new identity.
        """
        old_combos = id_to_combos.pop(old_id)
        new_combos.update(old_combos)
        for old_user, old_email in old_combos:
            if old_user and old_user != user:
                low_old_user = old_user.lower()
                old_user_id = username_to_id[low_old_user]
                if old_user_id not in (old_id, new_id):
                    raise AssertionError(f"{old_user_id} not in {old_id}, {new_id}")
                username_to_id[low_old_user] = new_id
            if old_email and old_email != email:
                old_email_id = email_to_id[old_email]
                if old_email_id not in (old_id, new_id):
                    raise AssertionError(f"{old_email_id} not in {old_id}, {new_id}")
                email_to_id[old_email] = cur_id

    for email, usernames in email_users.items():
        if email in email_to_id:
            raise AssertionError(f"{email} is already in {email_to_id}")
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
    for _cur_id, combos in id_to_combos.items():
        best_combo = sorted(combos, key=lambda x: combo_count[x], reverse=True)[0]
        for combo in combos:
            combo_to_best_combo[combo] = best_combo
    return combo_to_best_combo


def get_revisions_and_committers(a_repo, revids):
    """Get revision information and canonical committer mappings.

    Retrieves revision objects from the repository and builds a mapping
    to resolve committer identity conflicts by finding the canonical
    representation for each person.

    Args:
        a_repo: Repository object to fetch revisions from.
        revids: Iterable of revision IDs to process.

    Returns:
        Tuple containing:
            - Generator of revision objects
            - Dictionary mapping (username, email) tuples to canonical
              committer identities
    """
    email_users = {}  # user@email.com => User Name
    combo_count = {}
    with ui.ui_factory.nested_progress_bar() as pb:
        trace.note("getting revisions")
        revisions = list(a_repo.iter_revisions(revids))
        for count, (_revid, rev) in enumerate(revisions):
            pb.update("checking", count, len(revids))
            for author in rev.get_apparent_authors():
                # XXX: There is a chance sometimes with svn imports that the
                #      full name and email can BOTH be blank.
                username, email = config.parse_username(author)
                email_users.setdefault(email, set()).add(username)
                combo = (username, email)
                combo_count[combo] = combo_count.setdefault(combo, 0) + 1
    return (
        (rev for (revid, rev) in revisions),
        collapse_email_and_users(email_users, combo_count),
    )


def get_info(a_repo, revision):
    """Get comprehensive statistics information for a particular revision.

    Retrieves the complete ancestry of a revision and generates committer
    statistics by collapsing multiple identities for the same person.

    Args:
        a_repo: Repository object to analyze.
        revision: Revision ID to analyze ancestry for.

    Returns:
        List of tuples containing statistics grouped by person in format
        (commit_count, revisions_list, emails_dict, fullnames_dict).
    """
    with ui.ui_factory.nested_progress_bar(), a_repo.lock_read():
        trace.note("getting ancestry")
        graph = a_repo.get_graph()
        ancestry = [
            r
            for (r, ps) in graph.iter_ancestry([revision])
            if ps is not None and r != NULL_REVISION
        ]
        revs, canonical_committer = get_revisions_and_committers(a_repo, ancestry)

    return collapse_by_person(revs, canonical_committer)


def get_diff_info(a_repo, start_rev, end_rev):
    """Get statistics for new revisions between two revision points.

    This lets us figure out what has actually changed between 2 revisions
    by analyzing only the revisions that were added between the start
    and end points.

    Args:
        a_repo: Repository object to analyze.
        start_rev: Starting revision ID for comparison.
        end_rev: Ending revision ID for comparison.

    Returns:
        List of tuples containing statistics for the differential revisions
        in format (commit_count, revisions_list, emails_dict, fullnames_dict).
    """
    with ui.ui_factory.nested_progress_bar(), a_repo.lock_read():
        graph = a_repo.get_graph()
        trace.note("getting ancestry diff")
        ancestry = graph.find_difference(start_rev, end_rev)[1]
        revs, canonical_committer = get_revisions_and_committers(a_repo, ancestry)

    return collapse_by_person(revs, canonical_committer)


def display_info(info, to_file, gather_class_stats=None):
    """Display committer statistics information in a formatted output.

    Writes detailed statistics about committers including commit counts,
    alternative names, email addresses, and optionally contribution
    classifications.

    Args:
        info: List of tuples containing committer statistics in format
            (commit_count, revisions_list, emails_dict, fullnames_dict).
        to_file: File-like object to write output to.
        gather_class_stats: Optional callable that takes a revision list
            and returns (classes_dict, total_count) for contribution
            classification statistics.
    """
    for count, revs, emails, fullnames in info:
        # Get the most common email name
        sorted_emails = sorted(
            ((count, email) for email, count in emails.items()), reverse=True
        )
        sorted_fullnames = sorted(
            ((count, fullname) for fullname, count in fullnames.items()), reverse=True
        )
        if sorted_fullnames[0][1] == "" and sorted_emails[0][1] == "":
            to_file.write("%4d %s\n" % (count, "Unknown"))
        else:
            to_file.write(
                "%4d %s <%s>\n" % (count, sorted_fullnames[0][1], sorted_emails[0][1])
            )
        if len(sorted_fullnames) > 1:
            to_file.write("     Other names:\n")
            for count, fname in sorted_fullnames:
                to_file.write("     %4d " % (count,))
                if fname == "":
                    to_file.write("''\n")
                else:
                    to_file.write(f"{fname}\n")
        if len(sorted_emails) > 1:
            to_file.write("     Other email addresses:\n")
            for count, email in sorted_emails:
                to_file.write("     %4d " % (count,))
                if email == "":
                    to_file.write("''\n")
                else:
                    to_file.write(f"{email}\n")
        if gather_class_stats is not None:
            to_file.write("     Contributions:\n")
            classes, total = gather_class_stats(revs)
            for name, count in sorted(classes.items(), key=classify_key):
                if name is None:
                    name = "Unknown"
                to_file.write(f"     {float(count) / total * 100.0:4.0f}% {name}\n")


class cmd_committer_statistics(commands.Command):
    """Generate statistics for LOCATION.

    This command analyzes a Breezy repository to provide detailed statistics
    about committers, including commit counts, alternate names/emails used,
    and optionally the types of contributions made (code, documentation, etc.).

    The statistics can be generated for the entire history or for a specific
    revision range, helping to understand contributor patterns and activity.

    Attributes:
        aliases: Alternative command names 'stats' and 'committer-stats'.
        takes_args: Accepts optional location argument.
        takes_options: Accepts revision range and show-class options.
        encoding_type: Uses 'replace' encoding for output.
    """

    aliases = ["stats", "committer-stats"]
    takes_args = ["location?"]
    takes_options = [
        "revision",
        option.Option("show-class", help="Show the class of contributions."),
    ]

    encoding_type = "replace"

    def run(self, location=".", revision=None, show_class=False):
        """Execute the committer statistics command.

        Args:
            location: Path to the branch or working tree to analyze.
                Defaults to current directory.
            revision: Optional revision range to analyze. Can be a single
                revision or a range of two revisions.
            show_class: Whether to show contribution class statistics
                (code, documentation, art, translation).
        """
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
                info = get_diff_info(a_branch.repository, last_rev, alternate_rev)
            else:
                info = get_info(a_branch.repository, last_rev)
        if show_class:

            def fetch_class_stats(revs):
                """Fetch contribution class statistics for revisions.

                Args:
                    revs: List of revision objects to analyze.

                Returns:
                    Tuple of (classes_dict, total_count) for contribution statistics.
                """
                return gather_class_stats(a_branch.repository, revs)
        else:
            fetch_class_stats = None
        display_info(info, self.outf, fetch_class_stats)


class cmd_ancestor_growth(commands.Command):
    """Figure out the ancestor graph for LOCATION.

    This hidden command analyzes the growth of ancestors in the revision
    history, tracking how the number of ancestors changes over time.
    It outputs revision numbers paired with their ancestor counts,
    useful for understanding repository complexity and merge patterns.

    Attributes:
        takes_args: Accepts optional location argument.
        encoding_type: Uses 'replace' encoding for output.
        hidden: Command is hidden from normal help output.
    """

    takes_args = ["location?"]

    encoding_type = "replace"

    hidden = True

    def run(self, location="."):
        """Execute the ancestor growth analysis command.

        Analyzes the growth of ancestors over the revision history,
        outputting revision numbers and ancestor counts.

        Args:
            location: Path to the branch or working tree to analyze.
                Defaults to current directory.
        """
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
            sorted_graph = tsort.merge_sort(graph.iter_ancestry([last_rev]), last_rev)
            for cur_parents, (_num, _node_name, depth, _isend) in enumerate(
                reversed(sorted_graph), 1
            ):
                if depth == 0:
                    revno += 1
                    self.outf.write("%4d, %4d\n" % (revno, cur_parents))


def gather_class_stats(repository, revs):
    """Gather statistics about contribution classes from revisions.

    Analyzes revision deltas to classify contributions into categories
    such as code, documentation, art, and translation changes.

    Args:
        repository: Repository object to analyze.
        revs: List of revision objects to classify.

    Returns:
        Tuple containing:
            - Dictionary mapping class names to occurrence counts
            - Total number of classified contributions
    """
    ret = {}
    total = 0
    with ui.ui_factory.nested_progress_bar() as pb, repository.lock_read():
        for i, delta in enumerate(repository.get_revision_deltas(revs)):
            pb.update("classifying commits", i, len(revs))
            for c in classify_delta(delta):
                if c not in ret:
                    ret[c] = 0
                ret[c] += 1
                total += 1
    return ret, total


def classify_key(item):
    """Generate sort key for contribution classification items.

    Creates a sort key that orders items by count (descending) and then
    by name (ascending) for consistent sorting of classification results.

    Args:
        item: Tuple of (classification_name, count).

    Returns:
        Tuple suitable for use as a sort key.
    """
    return -item[1], item[0]


def display_credits(credits, to_file):
    """Display contributor credits organized by contribution type.

    Outputs credits information grouped into sections for different
    types of contributions (code, documentation, art, translations).

    Args:
        credits: Tuple containing four lists:
            (coders, documenters, artists, translators).
        to_file: File-like object to write output to.
    """
    (coders, documenters, artists, translators) = credits

    def print_section(name, lst):
        """Print a credits section with contributors.

        Args:
            name: Section name to display.
            lst: List of contributor names.
        """
        if len(lst) == 0:
            return
        to_file.write(f"{name}:\n")
        for name in lst:
            to_file.write(f"{name}\n")
        to_file.write("\n")

    print_section("Code", coders)
    print_section("Documentation", documenters)
    print_section("Art", artists)
    print_section("Translations", translators)


def find_credits(repository, revid):
    """Find the credits of the contributors to a revision.

    Analyzes the complete ancestry of a revision to determine contributor
    credits organized by the type of contribution they made.

    Args:
        repository: Repository object to analyze.
        revid: Revision ID to analyze ancestry for.

    Returns:
        Tuple containing four lists:
            (coders, documenters, artists, translators)
    """
    ret = {"documentation": {}, "code": {}, "art": {}, "translation": {}, None: {}}
    with repository.lock_read():
        graph = repository.get_graph()
        ancestry = [
            r
            for (r, ps) in graph.iter_ancestry([revid])
            if ps is not None and r != NULL_REVISION
        ]
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
        """Sort contributors by contribution count for a specific class.

        Args:
            name: Classification name to sort contributors for.

        Returns:
            List of contributor names sorted by contribution count.
        """
        return [author for author, _ in sorted(ret[name].items(), key=classify_key)]

    return (
        sort_class("code"),
        sort_class("documentation"),
        sort_class("art"),
        sort_class("translation"),
    )


class cmd_credits(commands.Command):
    """Determine credits for LOCATION.

    This command analyzes a repository to generate contributor credits
    organized by the type of contributions made. It classifies changes
    into categories like code, documentation, art, and translations,
    then lists contributors in each category based on their contribution
    frequency.

    Attributes:
        takes_args: Accepts optional location argument.
        takes_options: Accepts revision option to analyze specific revision.
        encoding_type: Uses 'replace' encoding for output.
    """

    takes_args = ["location?"]
    takes_options = ["revision"]

    encoding_type = "replace"

    def run(self, location=".", revision=None):
        """Execute the credits analysis command.

        Analyzes the repository to determine credits for contributors
        organized by type of contribution.

        Args:
            location: Path to the branch or working tree to analyze.
                Defaults to current directory.
            revision: Optional specific revision to analyze credits for.
                If not provided, uses the last revision.
        """
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
