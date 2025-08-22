#!/usr/bin/python3

"""Tool for finding which release a bug was fixed in by parsing NEWS files.

This script searches through NEWS files to determine in which release a specific
bug number was fixed, or finds entries matching a regular expression pattern.
It parses the structured format of Breezy NEWS files to extract bug information,
authors, release versions, and dates.
"""

# Simple script that will output the release where a given bug was fixed
# searching the NEWS file

import optparse
import re
import sys


class NewsParser:
    """Parser for Breezy NEWS files to extract bug fix information.

    This class implements a state machine to parse the structured format of
    NEWS files, extracting information about bugs that were fixed in each
    release along with author information and release dates.

    Attributes:
        paren_exp_re: Compiled regex for matching parenthetical expressions.
        release_re: Compiled regex for matching release lines.
        release_prefix_length: Length of the "brz " prefix in release lines.
        bugs_re: Compiled regex for matching bug numbers (e.g., #12345).
    """

    paren_exp_re = re.compile(r"\(([^)]+)\)")
    release_re = re.compile("brz[ -]")
    release_prefix_length = len("brz ")
    bugs_re = re.compile("#([0-9]+)")

    def __init__(self, news):
        """Initialize the NewsParser with a NEWS file handle.

        Args:
            news: File handle or iterable for the NEWS file to parse.
        """
        self.news = news
        # Temporary attributes used by the parser
        self.release = None
        self.date = None
        self.may_be_release = None
        self.release_markup = None
        self.entry = ""
        self.line = None
        self.lrs = None

    def set_line(self, line):
        """Set the current line being processed.

        Args:
            line: The current line from the NEWS file being processed.
        """
        self.line = line
        self.lrs = line.rstrip()

    def try_release(self):
        """Try to identify if the current line is a release header.

        Returns:
            bool: True if the line matches a release pattern, False otherwise.
        """
        if self.release_re.match(self.lrs) is not None:
            # May be a new release
            self.may_be_release = self.lrs
            # We know the markup will have the same length as the release
            self.release_markup = "#" * len(self.may_be_release)
            return True
        return False

    def confirm_release(self):
        """Confirm that a previously identified release line is valid.

        A release line is confirmed if it's followed by the appropriate
        markup line (a line of '#' characters matching the release length).

        Returns:
            bool: True if the release is confirmed, False otherwise.
        """
        if self.may_be_release is not None and self.lrs == self.release_markup:
            # The release is followed by the right markup
            self.release = self.may_be_release[self.release_prefix_length :]
            # Wait for the associated date
            self.date = None
            return True
        return False

    def try_date(self):
        """Try to parse a release date line.

        Looks for date information in various formats used in NEWS files,
        including both new format (:release_version: date) and old format
        (:Released: date).

        Returns:
            bool: True if a date was found and parsed, False otherwise.
        """
        if self.release is None:
            return False
        date_re = re.compile(
            rf":{self.release}: (NOT RELEASED YET|\d{{4}}-\d{{2}}-\d{{2}})"
        )
        match = date_re.match(self.lrs)
        if match is not None:
            self.date = match.group(1)
            return True
        # The old fashion way
        released_re = re.compile(r":Released:\s+(\d{4}-\d{2}-\d{2})")
        match = released_re.match(self.lrs)
        if match is not None:
            self.date = match.group(1)
            return True
        return False

    def add_line_to_entry(self):
        """Add the current line to the current NEWS entry being accumulated.

        Returns:
            bool: True if the line was added to the entry, False if it was empty.
        """
        if self.lrs == "":
            return False
        self.entry += self.line
        return True

    def extract_bugs_from_entry(self):
        """Possibly extract bugs from a NEWS entry and yield them.

        Not all entries will contain bugs and some entries are even garbage and
        we don't try to parse them (yet). The trigger is a '#' and what looks
        like a bug number inside parens to start with. From that we extract
        authors (when present) and multiple bugs if needed.
        """
        # FIXME: Malone entries are different
        # Join all entry lines to simplify multiple line matching
        flat_entry = " ".join(self.entry.splitlines())
        # Fixed bugs are always inside parens
        for par in self.paren_exp_re.findall(flat_entry):
            sharp = par.find("#")
            if sharp is not None:
                # We have at least one bug inside parens.
                bugs = list(self.bugs_re.finditer(par))
                if bugs:
                    # See where the first bug is mentioned
                    start = bugs[0].start()
                    end = bugs[-1].end()
                    if start == 0:
                        # (bugs/authors)
                        authors = par[end:]
                    else:
                        # (authors/bugs)
                        authors = par[:start]
                    for bug_match in bugs:
                        bug_number = bug_match.group(0)
                        yield (bug_number, authors, self.release, self.date, self.entry)
        # We've consumed the entry
        self.entry = ""

    def parse_bugs(self):
        """Parse the NEWS file and yield bug information.

        This is the main parsing method that processes the entire NEWS file
        line by line, maintaining state and yielding bug information as it's
        found.

        Yields:
            tuple: (bug_number, authors, release, date, entry) for each bug found.
        """
        for line in self.news:
            self.set_line(line)
            if self.try_release():
                continue  # line may a be release
            try:
                if self.confirm_release():
                    continue  # previous line was indeed a release
            finally:
                self.may_be_release = None
            if self.try_date():
                continue  # The release date has been seen
            if self.add_line_to_entry():
                continue  # accumulate in self.enrty
            yield from self.extract_bugs_from_entry()


def main():
    """Main entry point for the fixed-in script.

    Parses command line arguments and searches through the NEWS file for
    either a specific bug number or entries matching a regular expression.
    Prints information about where bugs were fixed.
    """
    opt_parser = optparse.OptionParser(
        usage="""Usage: %prog [options] BUG_NUMBER
    """
    )
    opt_parser.add_option(
        "-f",
        "--file",
        type="str",
        dest="news_file",
        help="NEWS file (defaults to ./NEWS)",
    )
    opt_parser.add_option(
        "-m",
        "--message",
        type="str",
        dest="msg_re",
        help="A regexp to search for in the news entry "
        "(BUG_NUMBER should not be specified in this case)",
    )
    opt_parser.set_defaults(news_file="./NEWS")
    (opts, args) = opt_parser.parse_args(sys.argv[1:])
    if opts.msg_re is not None:
        if len(args) != 0:
            opt_parser.error("BUG_NUMBER and -m are mutually exclusive")
        bug = None
        msg_re = re.compile(opts.msg_re)
    elif len(args) != 1:
        opt_parser.error(f"Expected a single bug number, got {args!r}")
    else:
        bug = args[0]

    news = open(opts.news_file)
    parser = NewsParser(news)
    try:
        seen = 0
        for b in parser.parse_bugs():
            (
                number,
                authors,
                release,
                date,
                entry,
            ) = b
            # indent entry
            entry = "\n".join(["    " + l for l in entry.splitlines()])
            found = False
            if bug is not None:
                if number[1:] == bug:  # Strip the leading '#'
                    found = True
            elif msg_re.search(entry) is not None:
                found = True
            if found:
                print(f"Bug {number} was fixed in brz-{release}/{date} by {authors}:")
                print(entry)
            seen += 1
    finally:
        print(f"{seen} bugs seen")
        news.close()


main()
