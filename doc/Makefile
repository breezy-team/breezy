%.html: %.txt
	rest2html $^ > $@.tmp && mv $@.tmp $@

all: $(addsuffix .html,$(basename $(wildcard *.txt)))


upload: all
	rsync -av *html escudero.ubuntu.com:/srv/www.bazaar-ng.org/www/doc/

