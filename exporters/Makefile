SVN ?= /usr
CFLAGS += -I${SVN}/include/subversion-1 -pipe -O2 -std=c99
CFLAGS += `pkg-config --cflags apr-1`
LDFLAGS += -L${SVN}/lib -lsvn_fs-1 -lsvn_repos-1
LDFLAGS += `pkg-config --libs apr-1`

all: svn-fast-export svn-archive

svn-fast-export: svn-fast-export.c
svn-archive: svn-archive.c

.PHONY: clean

clean:
	rm -rf svn-fast-export svn-archive
