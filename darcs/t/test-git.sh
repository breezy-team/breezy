rm -rf test.darcs test.git
mkdir test.git
cd test.git
git --bare init
cd ..
if [ "$1" != "--stdout" ]; then
	../darcs-fast-export.py test |(cd test.git; git fast-import)
	if [ $? = 0 ]; then
		git clone -q test.git test.git.nonbare
		echo "bugs:"
		diff --exclude _darcs --exclude .git -Naur test.git.nonbare test
		ret=$?
		rm -rf test.git.nonbare
		exit $?
	fi
else
	../darcs-fast-export.py test
fi
