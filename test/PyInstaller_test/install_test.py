import PyInstaller.__main__

# main python file name
# options = ['Dev8-Cavity-Lock.py']
options = ['./test/PyInstaller_test/GUI_test.py']

# app name
options += ['--name=PyInstaller_test']

# place the app
# default is in ./dist folder
options += ['--distpath=./test/PyInstaller_test/dist']

# place temporary work files
# default is in ./build folder
options += ['--workpath=./test/PyInstaller_test/build']

# place spec file
# default is in ./ (current working directory)
options += ['--specpath=./test/PyInstaller_test']

# Bundle all the files into a single executable file. 
# With this option, when the program starts, 
# (1) Windows needs to unpack all files and put in a temporary folder.
# It slows down program starting.
# The temporary folder can be access by sys._MEIPASS.
# Use os.path.join(sys.MEIPASS, relative_path) to find the path of a file in the temporary folder.
# (2) Windows thinks this program is a possible malware, and runs Antimalware Service Executable.
# It should be closed after a few seconds. Check task manager to see if the antimalware service is still running.
# options += ['--onefile']

# No terminal will open when the program starts.
options += ['--noconsole']

# run PyInstaller
PyInstaller.__main__.run(options)


# Unfortuantely, we can't use Nuitka to convert to a Windows executable at this moment,
# as it does not have good PyQt5 support.
# https://nuitka.net/pages/pyqt5.html
# Otherwise, it may provide a faster and more compact executable, since it translates Python into C.