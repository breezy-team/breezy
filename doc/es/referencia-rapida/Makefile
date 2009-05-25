TARGETS=referencia-rapida.png referencia-rapida.pdf
OBJECTS=referencia-rapida.svg Makefile

all: $(TARGETS)

.SUFFIXES: .svg .png .pdf

.svg.pdf:
	rsvg-convert -d 300 -p 300 -f pdf -o $@ $<

.svg.png:
	rsvg-convert -d 300 -p 300 -z 3.3346 -f png -o $@ $<

bzr-quickref.png: $(OBJECTS)

bzr-quickref.pdf: $(OBJECTS)

clean:
	rm -f $(TARGETS)
