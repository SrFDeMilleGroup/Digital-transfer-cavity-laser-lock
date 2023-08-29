import PyInstaller.__main__
import os


# main python file name
options = ['main.py']

# app name
options += ['--name=Dev8-Cavity-Lock']

# place the app in current folder
# default is in ./dist folder
# we don't use is here, because it comlicates base path choice in main.py.
# options += ['--distpath=.']

# Bundle all the files into a single executable file. 
# With this option, when the program starts, 
# (1) Windows needs to unpack all files and put in a temporary folder.
# It slows down program starting.
# The temporary folder can be access by sys._MEIPASS.
# Use os.path.join(sys.MEIPASS, relative_path) to find the path of a file in the temporary folder.
# (2) Windows thinks this program is a possible malware, and runs Antimalware Service Executable.
# It should be closed after a few seconds.
# Check task manager to see if the antimalware service is still running.s
# options += ['--onefile']

# No terminal will open when the program starts.
options += ['--noconsole']

# Add icon to the program.
# This is the icon you see in Windows file explorer.
# ./ means current folder (../ means parent folder)
options += ['--icon=./icon/Dev8-Cavity-Lock-Icon.ico']

# For some reason, nidaqmx needs this option to be added.
# https://stackoverflow.com/questions/71226142/pyinstaller-with-nidaqmx
options += ['--copy-metadata=nidaqmx']

# path to site packages
# default of PyInstaller.__file__ should be ....\AppData\Local\Programs\Python\Python310\lib\site-packages\PyInstaller\__init__.py
options += ['--paths=' + "\\".join(PyInstaller.__file__.split('\\')[:-2])]

# run PyInstaller
PyInstaller.__main__.run(options)


# This is to create a shortcut to the program in the current folder.
# follow https://stackoverflow.com/questions/26986470/create-shortcut-files-in-windows-7-using-python
import win32com.client
import os

currentfolder = os.path.dirname(__file__) # path to where you want to put the .lnk
path = os.path.join(currentfolder, 'Dev8-Cavity-Lock.lnk') # name of the shortcut
target_path = r"dist\Dev8-Cavity-Lock.exe" if "--onefile" in options else r"dist\Dev8-Cavity-Lock\Dev8-Cavity-Lock.exe"
target = os.path.join(currentfolder, target_path)
icon = os.path.join(currentfolder, r'icon\Dev8-Cavity-Lock-Icon.ico')

shell = win32com.client.Dispatch("WScript.Shell")
shortcut = shell.CreateShortCut(path)
shortcut.Targetpath = target
shortcut.IconLocation = icon
shortcut.save()


# Unfortuantely, we can't use Nuitka to convert to a Windows executable at this moment,
# as it does not have good PyQt5 support.
# https://nuitka.net/pages/pyqt5.html
# Otherwise, it may provide a faster and more compact executable, since it translates Python into C.