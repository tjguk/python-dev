import os, sys
import argparse
try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import SafeConfigParser as ConfigParser
import fnmatch
import glob
import logging
import shutil
import subprocess

try:
    basestring
except NameError:
    basestring = str

LOG_FILEPATH = "make.log"

logger = logging.getLogger(os.path.basename(__file__))

def _check_output(*args, **kwargs):
    return subprocess.check_output(*args, **kwargs).strip().decode(sys.stdout.encoding)

def _file_operation(pattern, start_from=".", recursive=False):
    """Common file-matching semantics:

    Search for files whose name matches [pattern].
    By default, search the current directory but a specific directory or iterable
    of directories can be specified, in which case it and (optionally) all its
    children will be searched.
    """
    if isinstance(start_from, basestring):
        paths = [start_from]
    else:
        paths = start_from

    for path in paths:
        if not os.path.exists(path):
            continue
        if recursive:
            for dirpath, dirnames, filenames in os.walk(path):
                for filename in filenames:
                    if fnmatch.fnmatch(filename, pattern):
                        yield os.path.join(dirpath, filename)
        else:
            for filepath in glob.glob(os.path.join(path, pattern)):
                yield filepath

def _where(pattern, start_from=None, recursive=False):
    """Search for a file whose name matches [pattern].

    By default, search the current directory and the PATH but a
    specific directory can be specified, in which case it and (optionally)
    all its children will be searched.
    """
    logger.info("Looking for %s in %s", pattern, start_from)
    if start_from is None:
        start_from = ["."] + [p for p in os.environ["PATH"].split(";")]
    for filepath in _file_operation(pattern, start_from, recursive):
        return filepath

def _delete(pattern, start_from=".", recursive=False, callback=None):
    """delete files who names match [pattern].

    By default, search the current directory but a specific directory
    can be specified. Recursion may be used but, by default, is not.
    """
    logger.info("About to delete %s from %s", pattern, start_from or ".")
    for filepath in _file_operation(pattern, start_from, recursive):
        os.unlink(filepath)
        if callback:
            callback(filepath)

def _rmdir(start_from, callback=None):
    """Remove a directory and everything underneath it
    """
    logger.info("About to rmdir %s", start_from)
    for dirpath, _, filenames in os.walk(start_from, topdown=False):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if callback:
                callback.callback(filepath)
            os.unlink(filepath)
        os.rmdir(dirpath)

class Config(object):

    #
    # Defaults
    #
    configuration = "Debug"
    platform = "Win32"
    interactive = True
    externals = True

    def __init__(self):
        self.root = os.getcwd()
        self.here = os.path.dirname(os.path.abspath(__file__))
        try:
            self.branch = _check_output("hg branch")
        except subprocess.CalledProcessError:
            logger.warn("Can't determine hg branch; using default")
            self.branch = "default"
        parser = ConfigParser()
        parser.read([
            os.path.join(self.here, "configure.ini"),
            os.path.join(self.here, "configure.%s.ini" % self.branch),
            os.path.join(self.root, "configure.ini"),
        ])
        self.config = parser.get("configure", "configuration", fallback=self.__class__.configuration)
        self.platform = parser.get("configure", "platform", fallback=self.__class__.platform)
        self.visual_studio = os.path.abspath(os.environ[parser.get("configure", "envvar")])
        self.svnroot = parser.get("locations", "svnroot")
        self.externals = dict(parser.items("externals"))

        self.pcbuild = os.path.join(self.root, "PCBuild")
        self.externals_dir = os.path.abspath(os.path.join(self.pcbuild, "../.."))
        if self.platform == "x64":
            self.vcvarsarg = "x86_amd64"
            self.pybuilddir = os.path.join(self.pcbuild, "amd64")
        else:
            self.vcvarsarg = "x86"
            self.pybuilddir = self.pcbuild
        pybuildextension = "_d.exe" if self.configuration == "Debug" else ".exe"
        self.python_exe = os.path.join(self.pybuilddir, "python" + pybuildextension)

    def dumped(self):
        content = []
        content.append("{")
        for name in sorted(dir(self)):
            if name.startswith("_"):
                continue
            attr = getattr(self, name)
            if callable(attr):
                continue
            content.append("  %s => %r" % (name, attr))
        content.append("}")
        return "\n".join(content)

class Build(object):

    def __init__(self, config, stdout):
        self.config = config
        self.stdout = stdout

    @classmethod
    def valid_targets(cls):
        return set(m[3:] for m in dir(cls) if m.startswith("do_"))

    def _run_command(self, command, *args, **kwargs):
        p = subprocess.Popen(command, *args, stdout=self.stdout, stderr=subprocess.STDOUT, **kwargs)
        if p.wait() != 0:
            raise RuntimeError("Problem with command")

    def _find_interpreter(self):
        """Attempt to find an interpreter:

        * If a PYTHON3 env var is set, return its value
        * If a python.bat exists in the current directory, return that
        * If a python*.exe exists in the PCBuild directory, return that
        * If a py.exe exists any_where on the path, return that
        * Otherwise, return "python" and hope for the best

        NB This should not be run and cached, as the interpreter may not
        exist until it has been built.
        """
        if "PYTHON3" in os.environ:
            return os.environ["PYTHON3"]
        if os.path.exists(os.path.join(self.config.root, "python.bat")):
            return "python.bat"
        pcbuild_exe = _where("python*.exe", self.config.pcbuild, True)
        if pcbuild_exe:
            return pcbuild_exe
        py_exe = _where("py.exe")
        if py_exe:
            return py_exe
        return "python"

    def msbuild(self, project, target, **kwargs):
        vcvarsall = os.path.join(self.config.visual_studio, r"..\..\VC\vcvarsall.bat")
        params = ["/p:%s=%s" % (k, v) for (k, v) in kwargs.items()]
        msbuild = ["msbuild", "/target:%s" % target, project] + params
        logger.debug(msbuild)
        logger.info("Running msbuild %s", target)
        return self._run_command(["call", vcvarsall, self.config.vcvarsarg, "&&"] + msbuild, shell=True)

    def build_solution(self, target, **kwargs):
        return self.msbuild(r"PCbuild\pcbuild.sln", target, **kwargs)

    def check_externals(self):
        for name, version in self.config.externals.items():
            target_dirpath = os.path.abspath(os.path.join(self.config.externals_dir, version))
            if not os.path.exists(target_dirpath):
                logger.warn("External %s is not in place", version)

    def do_all(self):
        self.do_clean()
        self.do_externals()
        self.do_build()
        self.do_test()

    def do_build(self):
        """Build CPython"""
        logger.info("Build & run kill_python")
        self.msbuild(
            r"PCbuild\kill_python.vcxproj",
            "Build",
            Config="Debug",
            PlatformTarget=self.config.platform
        )
        self._run_command([os.path.join(self.config.pybuilddir, "kill_python_d.exe")])
        _delete(self.config.python_exe)
        logger.info("Check externals")
        self.check_externals()
        logger.info("Build Python")
        self.build_solution(
            "Build",
            Config=self.config.configuration,
            Platform=self.config.platform
        )

    def do_buildbottest(self):
        """Test Python with default options for buildbots"""
        raise NotImplementedError

    def do_clean(self):
        """Clean out build artifacts for current configuration"""
        logger.info("Deleting .pyc / .pyo files")
        _delete("*.pyc", self.config.root, True, callback=logger.debug)
        _delete("*.pyo", self.config.root, True, callback=logger.debug)
        _rmdir(os.path.join(self.config.root, "build"), callback=logger.debug)
        for configuration in "Release", "Debug":
            self.build_solution("clean", Config=configuration, Platform=self.config.platform)
        _delete("python.bat", callback=logger.debug)

    def do_clobber(self):
        """Clean out all build artifacts and remove externals"""
        self.do_clean()
        _delete("tcl*.dll", "PCbuild", recursive=True)
        _delete("tk*.dll", "PCbuild", recursive=True)
        for name, version in self.config.externals.items():
            target_dirpath = os.path.abspath(os.path.join(self.config.externals_dir, version))
            _rmdir(target_dirpath, callback=logger.debug)

    def do_externals(self):
        """Fetch external libraries in preparation for building"""
        for name, version in self.config.externals.items():
            target_dirpath = os.path.join(self.config.externals_dir, version)
            if os.path.exists(target_dirpath):
                logger.warn("Not fetching %s; already exists", version)
            else:
                logger.info("Fetching %s into %s", version, target_dirpath)
                self._run_command(["svn", "export", "%s/%s" % (self.config.svnroot, version), target_dirpath])

    def do_importlib(self):
        """Build and run the _freeze_importlib project"""
        already_exists = set(glob.glob(r"PCBuild\python*.exe"))
        self.msbuild(
            r"PCbuild\_freeze_importlib.vcxproj",
            "Build",
            Config="Release",
            PlatformTarget=self.config.platform
        )
        for python_exe in glob.glob(r"PCBuild\python*.exe"):
            if python_exe not in already_exists:
                logger.warn("Removing %s because build artefact", python_exe)
                os.unlink(python_exe)

    def do_msi(self):
        """Build a Python .msi"""
        raise NotImplementedError

    def do_patchcheck(self):
        r"""Run Tools\scripts\patchcheck.py"""
        raise NotImplementedError

    def do_tcltk(self):
        """Build Tcl/Tk and install .dlls"""
        raise NotImplementedError

    def do_test(self):
        """Test Python"""
        python_exe = os.path.abspath(self._find_interpreter())
        args = [python_exe,
                '-W', 'default',      # Warnings set to 'default'
                '-bb',                # Warnings about bytes/bytearray
                '-E',                 # Ignore environment variables
                ]
        args.extend(['-W', 'error::BytesWarning'])
        args.extend(['-m', 'test',    # Run the test suite
                     '-r',            # Randomize test order
                     ])
        args.append('-n')         # Silence alerts under Windows
        logger.info("About to run tests with %s", args)
        self._run_command(args)

def main(*args):
    formatter = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')
    logger.setLevel(level=logging.INFO)
    screen = logging.StreamHandler(sys.stdout)
    screen.setFormatter(formatter)
    logger.addHandler(screen)

    with open(LOG_FILEPATH, "w") as stdout:
        stdout_handler = logging.StreamHandler(stdout)
        stdout_handler.setFormatter(formatter)
        logger.addHandler(stdout_handler)

        config = Config()
        logger.info(config.dumped())
        builder = Build(config, stdout)
        valid_targets = builder.valid_targets()
        logger.info("Valid targets: %s", ", ".join (builder.valid_targets()))

        if args:
            targets = list(args)
        else:
            targets = ["all"]
        for target in targets:
            if target not in valid_targets:
                logger.warn("Unknown target: %s; ignoring...", target)
            else:
                logger.info("Executing %s", target)
                function = getattr(builder, "do_" + target)
                function()

if __name__ == '__main__':
    main(*sys.argv[1:])
