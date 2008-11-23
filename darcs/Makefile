VERSION = 0.5
DATE := $(shell date +%Y-%m-%d)

MAN_TXT = $(wildcard *.txt)
MAN_HTML=$(patsubst %.txt,%.html,$(MAN_TXT))
MAN=$(patsubst %.txt,%.1,$(MAN_TXT))

doc: HEADER.html Changelog

HEADER.html: README Makefile
	asciidoc -a toc -a numbered -a sectids -o HEADER.html README

Changelog: .git/refs/heads/master
	git log --no-merges |git name-rev --tags --stdin >Changelog

%.html: %.txt
	asciidoc $^

%.1: %.txt asciidoc.conf
	a2x --asciidoc-opts="-f asciidoc.conf" \
		-a dfe_version=$(VERSION) -a dfe_date=$(DATE) -f manpage $<

man: $(MAN)

html: $(MAN_HTML)
