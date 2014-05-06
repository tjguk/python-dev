#!python3
import os, sys
import html.parser
import re
import subprocess
import urllib.request

import pythoncom
from win32com.shell import shell, shellcon

class HTMLParser(html.parser.HTMLParser):

    def __init__(self):
        html.parser.HTMLParser.__init__(self)
        self.found_title = False
        self.title = ""
    
    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.found_title = True
    
    def handle_endtag(self, tag):
        if tag == "title":
            self.found_title = False
    
    def handle_data(self, data):
        if self.found_title:
            self.title += data.strip()

def clone_from_title(url, title):
    match = re.match(r"Issue\s+(\d+)\:\s+(.*?) - Python tracker", title)
    if match:
        number, name = match.groups()
    else:
        raise RuntimeError("No suitable title found for %s" % url)
    
    #
    # Strip out unwanted characters and convert to
    # a dash-separated string starting with issuexxxxx
    #
    name = name.lower()
    name = name.replace(".", " ")
    name = name.replace("_", " ")
    name = "-".join(name.split())
    clone_name = "issue%s-%s" % (number, name)
    subprocess.check_output(["hg", "clone", "hg.python.org", clone_name])
    
    #
    # Create a shortcut inside the new clone pointing to
    # the issue page in bugs.python.org
    #
    shortcut = pythoncom.CoCreateInstance (
      shell.CLSID_InternetShortcut,
      None,
      pythoncom.CLSCTX_INPROC_SERVER,
      shell.IID_IUniformResourceLocator
    )
    shortcut.SetURL(url)
    persist_file = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
    persist_file.Save(os.path.join(clone_name, "bugs.python.org.url"), 0)
    
    return clone_name

def main(url):
    page = urllib.request.urlopen(url)
    parser = HTMLParser()
    parser.feed(page.read().decode("utf-8"))
    if not parser.title:
        raise RuntimeError("No title found for %s" % url)
    print(clone_from_title(url, parser.title))

if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
