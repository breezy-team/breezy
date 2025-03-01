#!/usr/bin/python3

# Simple script that will output the release where a given bug was fixed
# searching the NEWS file

import optparse
import re
import sys


class NewsParser:
    paren_exp_re = re.compile(r"\(([^)]+)\)")
    release_re = re.compile("brz[ -]")
    release_prefix_length = len("brz ")
    bugs_re = re.compile("#([0-9]+)")

    def __init__(self, news):
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
        self.line = line
        self.lrs = line.rstrip()

    def try_release(self):
        if self.release_re.match(self.lrs) is not None:
            # May be a new release
            self.may_be_release = self.lrs
            # We know the markup will have the same length as the release
            self.release_markup = "#" * len(self.may_be_release)
            return True
        return False

    def confirm_release(self):
        if self.may_be_release is not None and self.lrs == self.release_markup:
            # The release is followed by the right markup
            self.release = self.may_be_release[self.release_prefix_length :]
            # Wait for the associated date
            self.date = None
            return True
        return False

    def try_date(self):
        if self.release is None:
            return False
        date_re = re.compile(
            r":{}: (NOT RELEASED YET|\d{{4}}-\d{{2}}-\d{{2}})".format(self.release)
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
        opt_parser.error("Expected a single bug number, got {!r}".format(args))
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
                print(
                    "Bug {} was fixed in brz-{}/{} by {}:".format(
                        number, release, date, authors
                    )
                )
                print(entry)
            seen += 1
    finally:
        print("{} bugs seen".format(seen))
        news.close()


main()
