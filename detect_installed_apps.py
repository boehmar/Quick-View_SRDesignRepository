from windows_tools.installed_software import get_installed_software
import sys
import subprocess
import os

#with open('scriptresult.txt', 'w') as f:
#    with redirect_stdout(f):

file_path = "scriptresult.txt"
if os.path.exists(file_path):
  with open(file_path, "w") as file: # "w" sets open in write mode
    for software in get_installed_software():
      file.write(f"{software['name']} {software['version']} {software['publisher']}\n")
  #print(software['name'], software['version'], software['publisher'])
else:
  print("The file does not exist")
