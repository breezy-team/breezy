rm -rf test.darcs test.bzr
mkdir test.bzr
cd test.bzr
bzr init-repo .
cd ..
if [ "$1" != "--stdout" ]; then
	../darcs-fast-export.py test |(cd test.bzr; bzr fast-import -)
	if [ $? = 0 ]; then
		bzr branch test.bzr/master test.bzr.nonbare
		echo "bugs:"
		diff --exclude .bzr -Naur test.bzr.nonbare test/_darcs/pristine
		rm -rf test.bzr.nonbare
	fi
else
	../darcs-fast-export.py test
fi
