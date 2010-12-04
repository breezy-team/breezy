TARGETS=bzr-es-quick-reference.png bzr-es-quick-reference.pdf
OBJECTS=bzr-es-quick-reference.svg Makefile

all: $(TARGETS)

.SUFFIXES: .svg .png .pdf

.svg.pdf:
	rsvg-convert -d 300 -p 300 -f pdf -o $@ $<

.svg.png:
	rsvg-convert -d 300 -p 300 -z 3.3346 -f png -o $@ $<

bzr-es-quick-reference.png: $(OBJECTS)

bzr-es-quick-reference.pdf: $(OBJECTS)

clean:
	rm -f $(TARGETS)
