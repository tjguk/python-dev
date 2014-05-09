#!python3
import os, sys
import html.parser
import re
import string
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
    valid = set(string.ascii_lowercase + string.digits + " ")
    name = "".join((c if c in valid else " ") for c in name.lower())
    name = "-".join(name.split()[:8])
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
    path = os.path.abspath(os.path.join(clone_name, "bugs.python.org.url"))
    persist_file.Save(path, 0)

    return clone_name

def main(url):
    """Take a bugs.python.org URL, an issue name or an issue number and
    generate a fresh clone with the issue number and (possibly abbreviated)
    name. Add a .url link inside pointing to the issue page.

    NB be careful not to output anything to stdout except for the
    directory created; a convenience clone.cmd will read the output
    and cd.
    """
    url = url.lower().strip()
    if url.isdigit():
        url = "issue%s" % url
    if url.startswith("issue"):
        url = "http://bugs.python.org/%s" % url
    page = urllib.request.urlopen(url)
    parser = HTMLParser()
    parser.feed(page.read().decode("utf-8"))
    if not parser.title:
        raise RuntimeError("No title found for %s" % url)
    print(clone_from_title(url, parser.title))

if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
