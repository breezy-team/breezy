all:

check:
	./bzr selftest -v $(tests)
	@echo "Running all tests with no locale."
	LC_CTYPE= LANG=C LC_ALL= ./bzr selftest -v $(tests)

check-msgeditor:
	./bzr --no-plugins selftest -v msgeditor

# Run Python style checker (apt-get install pyflakes)
pyflakes:
	pyflakes bzrlib

pyflakes-nounused:
	# There are many of these warnings at the moment and they're not a
	# high priority to fix
	pyflakes bzrlib | grep -v ' imported but unused'

clean:
	./setup.py clean
	-find . -name "*.pyc" -o -name "*.pyo" | xargs rm -f
	rm -rf test????.tmp

.PHONY: all


# build emacs cross-reference
tag_files=./bzr ./bzrlib/*py ./bzrlib/selftest/*.py
TAGS: $(tag_files)
	ctags-exuberant -e $(tag_files)


# make bzr.exe for win32 with py2exe
exe:
	@echo Make bzr.exe
	python setup.py py2exe > py2exe.log
	copy /Y tools\win32\start_bzr.bat win32_bzr.exe\start_bzr.bat
	copy /Y tools\win32\bazaar.url win32_bzr.exe\bazaar.url

# translate txt docs to html
doc_dir := doc 
txt_files := $(wildcard $(addsuffix /*.txt, $(doc_dir)))
htm_files := $(patsubst %.txt, %.htm, $(txt_files)) doc/bzr_man.htm

%.htm: %.txt
	rst2html.py --link-stylesheet --stylesheet=default.css $*.txt $*.htm

doc/bzr_man.txt:
	generate_docs.py -o doc/bzr_man.txt rstx

docs: $(htm_files)

copy_docs: docs
	copy /Y NEWS win32_bzr.exe\NEWS
	copy /Y README win32_bzr.exe\README
	python tools/win32/copy_docs.py

# win32 installer for bzr.exe
installer: exe copy_docs
	@echo Make windows installer
	cog.py -d -o tools\win32\bzr.iss tools\win32\bzr.iss.cog
	iscc /Q tools\win32\bzr.iss

# win32 python's distutils-based installer
# require to have python interpreter installed on win32
python-installer: docs
	python setup.py bdist_wininst --title="Bazaar" --install-script="bzr-win32-bdist-postinstall.py"


# clean on win32 all installer-related files and directories
clean_win32:
	if exist build rmdir /S /Q build
	if exist win32_bzr.exe rmdir /S /Q win32_bzr.exe
	if exist py2exe.log del /Q py2exe.log
	if exist doc\*.htm del /Q doc\*.htm
	if exist doc\bzr_man.txt del /Q doc\bzr_man.txt
	if exist tools\win32\bzr.iss del /Q tools\win32\bzr.iss
	if exist bzr-setup*.exe del /Q bzr-setup*.exe
	if exist dist rmdir /S /Q dist
