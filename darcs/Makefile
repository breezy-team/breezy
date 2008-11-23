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

%.1: %.txt
	a2x -f manpage $<

man: $(MAN)

html: $(MAN_HTML)
