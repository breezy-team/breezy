all: $(addsuffix .html,$(basename $(wildcard *.txt))) todo.html

clean:
	-rm *.html

%.html: %.txt
	rest2html $^ > $@.tmp && mv $@.tmp $@

todo.html: ../TODO
	rest2html $^ > $@.tmp && mv $@.tmp $@



upload: all
	rsync -av \
	./ \
	escudero.ubuntu.com:/srv/www.bazaar-ng.org/www/doc/ \
	--delete \
	--include \*.html --exclude \* 

