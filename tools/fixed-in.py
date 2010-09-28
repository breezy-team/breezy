#!/usr/bin/python

# Simple script that will output the release where a given bug was fixed
# searching the NEWS file

import optparse
import re
import sys


class NewsParser(object):

    paren_exp_re = re.compile('\(([^)]+)\)')
    release_re = re.compile("bzr[ -]")
    release_prefix_length = len('bzr ')
    bugs_re = re.compile('#([0-9]+)')

    def __init__(self, news):
        self.news = news
        # Temporary attributes used by the parser
        self.relese = None
        self.may_be_release = None
        self.release_markup = None
        self.entry = ''
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
            self.release_markup = '#' * len(self.may_be_release)
            return True
        return False

    def confirm_release(self):
        if self.may_be_release is not None and self.lrs == self.release_markup:
            # The release is followed by the right markup
            self.release = self.may_be_release[self.release_prefix_length:]
            return True
        return False

    def add_line_to_entry(self):
        if self.lrs == '':
            return False
        self.entry += self.line
        return True

    def extract_bugs_from_entry(self):
        # Not all entries will contain bugs and some entries are even garbage
        # that is not parsed (yet).
        # FIXME: Malone entries are different
        # Join all entry lines to simplify multiple line matching
        flat_entry = ' '.join(self.entry.splitlines())
        # Fixed bugs are always inside parens
        for par in self.paren_exp_re.findall(flat_entry):
            sharp = par.find('#')
            if sharp is not None:
                bugs = list(self.bugs_re.finditer(par))
                if bugs:
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
                        yield (bug_number, authors, self.release, self.entry)
        # We've consumed the entry
        self.entry = ''

    def parse_bugs(self):
        for line in self.news:
            self.set_line(line)
            if self.try_release():
                continue
            try:
                if self.confirm_release():
                    continue
            finally:
                self.may_be_release = None
            if self.add_line_to_entry():
                continue
            for b in self.extract_bugs_from_entry():
                yield b

def main():
    opt_parser = optparse.OptionParser(
        usage="""Usage: %prog [options] <bug_number>
    """)
    opt_parser.add_option('-f', '--file', type='str', dest='news_file',
                          help='NEWS file (defaults to ./NEWS)')
    opt_parser.set_defaults(news_file='./NEWS')

    (opts, args) = opt_parser.parse_args(sys.argv[1:])
    if len(args) != 1:
        opt_parser.error('Expected a single bug number, got %r' % args)

    bug = args[0]

    news = open(opts.news_file)
    parser = NewsParser(news)
    try:
        seen = 0
        for b in parser.parse_bugs():
            #(number, release, date, author, entry) = b
            (number, authors, release, entry,) = b
            (date,) = ('2010-01-01',)
            # indent entry
            entry = '\n'.join(['    ' + l for l in entry.splitlines()])
            if number[1:] == bug: # Strip the leading '#'
                print 'Bug %s was fixed in bzr-%s by %s:' % (
                    number, release, authors)
                print entry
            seen += 1
    finally:
        print '%s bugs seen' % (seen,)
        news.close()


main()
