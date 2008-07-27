
set-item env:LIB -value "C:\Program Files\Microsoft Visual C++ Toolkit 2003\lib"
set-item env:INCLUDE -value "C:\Program Files\Microsoft Visual C++ Toolkit 2003\include"

rm -r -for build

python setup.py build_ext

cp -for build\lib.win32-2.5\bzrlib\plugins\svn\*.pyd .\
