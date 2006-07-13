import glob
import os
import shutil

TGT_DIR = 'win32_bzr.exe/doc'

if not os.path.exists(TGT_DIR):
    os.makedirs(TGT_DIR)

for i in glob.glob('doc/*.htm'):
    shutil.copy(i, os.path.join('win32_bzr.exe', i))

CSS = 'doc/default.css'
if os.path.isfile(CSS):
    shutil.copy(CSS, os.path.join('win32_bzr.exe', CSS))
