%.html: %.txt
	rest2html $^ > $@.tmp && mv $@.tmp $@

all: $(addsuffix .html,$(basename $(wildcard *.txt)))


upload: all
	(echo 'cd www'; ls *html | sed -e 's/^/put /') | sftp -b /dev/fd/0 bazng@escudero.ubuntu.com
