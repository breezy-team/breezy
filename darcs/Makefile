doc: HEADER.html Changelog

HEADER.html: README Makefile
	asciidoc -a toc -a numbered -a sectids -o HEADER.html README

Changelog: .git/refs/heads/master
	git log --no-merges |git name-rev --tags --stdin >Changelog
