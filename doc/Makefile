%.html: %.txt
	rest2html $^ > $@.tmp && mv $@.tmp $@

all: $(addsuffix .html,$(basename $(wildcard *.txt)))


upload: all
	rsync -av \
	./ \
	escudero.ubuntu.com:/srv/www.bazaar-ng.org/www/doc/ \
	--delete \
	--include \*.html --exclude \* 

