VERSION = 0.9
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
	git log >Changelog

%.html: %.txt
	asciidoc $^

%.1: %.txt asciidoc.conf
	a2x --asciidoc-opts="-f asciidoc.conf" \
		-a dfe_version=$(VERSION) -a dfe_date=$(DATE) -f manpage $<

man: $(MAN)

html: $(MAN_HTML)

dist:
	git archive --format=tar --prefix=darcs-fast-export-$(VERSION)/ $(VERSION) > darcs-fast-export-$(VERSION).tar
	mkdir -p darcs-fast-export-$(VERSION)
	git log > darcs-fast-export-$(VERSION)/Changelog
	tar rf darcs-fast-export-$(VERSION).tar darcs-fast-export-$(VERSION)/Changelog
	rm -rf darcs-fast-export-$(VERSION)
	gzip -f -9 darcs-fast-export-$(VERSION).tar

release:
	git tag -l |grep -q $(VERSION) || dg tag $(VERSION)
	$(MAKE) dist
	gpg --comment "See http://vmiklos.hu/gpg/ for info" \
		-ba darcs-fast-export-$(VERSION).tar.gz
