VERSION = 0.5
DATE := $(shell date +%Y-%m-%d)

INSTALL = /usr/bin/install -c
DESTDIR =
prefix = /usr
bindir = $(prefix)/bin
mandir = $(prefix)/share/man/man1

MAN_TXT = $(wildcard *.txt)
MAN_HTML=$(patsubst %.txt,%.html,$(MAN_TXT))
MAN=$(patsubst %.txt,%.1,$(MAN_TXT))

PROGRAMS = darcs-fast-export darcs-fast-import d2x x2d git-darcs

all: man

install: all
	$(INSTALL) -d $(DESTDIR)$(bindir)
	$(INSTALL) -d $(DESTDIR)$(mandir)
	$(INSTALL) -m755 $(PROGRAMS) $(DESTDIR)$(bindir)
	$(INSTALL) -m644 *.1 $(DESTDIR)$(mandir)

doc: HEADER.html Changelog html

HEADER.html: README Makefile
	asciidoc -a toc -a numbered -a sectids -o HEADER.html README

Changelog: .git/refs/heads/master
	git log --no-merges |git name-rev --tags --stdin >Changelog

%.html: %.txt
	asciidoc $^

%.1: %.txt asciidoc.conf
	a2x --asciidoc-opts="-f asciidoc.conf" \
		-a dfe_version=$(VERSION) -a dfe_date=$(DATE) -f manpage $<
	if echo $@ |grep -q -- -; then mv $(shell echo $@ |tr - _) $@; fi

man: $(MAN)

html: $(MAN_HTML)
