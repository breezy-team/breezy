#!/usr/bin/python

# Simple script that will output the release where a given bug was fixed
# searching the NEWS file

import optparse
import re
import sys


opt_parser = optparse.OptionParser(
    usage="""Usage: %prog [options] <bug_number>
""")
opt_parser.add_option('-f', '--file', type='str', dest='news_file',
                      help='NEWS file (defaults to ./NEWS)')
opt_parser.set_defaults(news_file='./NEWS')


class NewsParser(object):

    release_re = re.compile("bzr[ -]")
    release_prefix_length = len('bzr ')

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
            print 'Release: [%s]' % (self.release,)
            return True
        return False

    def parse_bugs(self):
        for line in self.news:
            self.set_line(line)
            if self.try_release():
                continue
            try:
                if self.confirm_release():
                    yield (self.release,)
                    continue
            finally:
                self.may_be_release = None


def main():
    (opts, args) = opt_parser.parse_args(sys.argv[1:])
    if len(args) != 1:
        opt_parser.error('Expected a single bug number, got %r' % args)

    bug = args[0]

    news = open(opts.news_file)
    parser = NewsParser(news)
    try:
        for b in parser.parse_bugs():
            #(number, release, date, author, entry) = b
            (release,) = b
            (number, date, author, entry) = (123, '2010-01-01', 'joe',
                                             '(joe, #123)')
            # indent entry
            entry = '\n'.join(['    ' + l for l in entry.splitlines()])
            if number == bug:
                print 'Bug #%s was fixed in bzr-%s:' % (number, release)
                print entry
    finally:
        news.close()


main()
