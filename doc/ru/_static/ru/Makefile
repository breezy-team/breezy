TARGETS=bzr-quick-reference.png bzr-quick-reference.pdf
OBJECTS=bzr-quick-reference.svg Makefile

all: $(TARGETS)

.SUFFIXES: .svg .png .pdf

.svg.pdf:
	rsvg-convert -d 300 -p 300 -f pdf -o $@ $<

.svg.png:
	rsvg-convert -d 300 -p 300 -z 3.3346 -f png -o $@ $<

bzr-quick-reference.png: $(OBJECTS)

bzr-quick-reference.pdf: $(OBJECTS)

clean:
	rm -f $(TARGETS)
