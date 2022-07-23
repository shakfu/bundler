#!/usr/bin/env python3
"""bundler.py

Provides functional tools to make an .app bundle

- make_bundle() requires macholib
- get_deps() recursively returns dependencies

"""
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Set, Union

from macholib import macho_standalone


Pathlike = Union[Path, str]

PATTERNS = [
    "/opt/local/",
    "/usr/local/",
    "/Users/",
    "/tmp/",
]


INFO_PLIST_TMPL = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>English</string>
    <key>CFBundleExecutable</key>
    <string>{executable}</string>
    <key>CFBundleGetInfoString</key>
    <string>{versioned_bundle_name}</string>
    <key>CFBundleIconFile</key>
    <string>app.icns</string>
    <key>CFBundleIdentifier</key>
    <string>{bundle_identifier}</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>{bundle_name}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>{versioned_bundle_name}</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleVersion</key>
    <string>{bundle_version}</string>
    <key>NSAppleScriptEnabled</key>
    <string>YES</string>
    <key>NSMainNibFile</key>
    <string>MainMenu</string>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>
"""


def make_bundle(target: Pathlike, version: str = "1.0", 
                add_to_resources: list[str] = None, prefix: str = "org.me", 
                suffix: str = ".app"):
    """Makes a macos bundle.

    :param      target:   The target executable
    :type       target:   str
    :param      version:  The version; defaults to '1.0'
    :type       version:  str
    :param      prefix:   The prefix of the bundle id; defaults to 'org.me'
    :type       prefix:   str
    :param      prefix:   The suffix of the bundle; defaults to '.app'
    :type       prefix:   str
    """
    target = Path(target)
    bundle = target.parent / (target.stem + suffix)
    bundle_contents = bundle / "Contents"

    bundle_info_plist = bundle_contents / "Info.plist"
    bundle_pkg_info = bundle_contents / "PkgInfo"

    bundle_macos = bundle_contents / "MacOS"
    bundle_frameworks = bundle_contents / "Frameworks"
    bundle_resources = bundle_contents / "Resources"

    bundle_subdirs = [bundle_macos, bundle_frameworks]

    bundle_executable = bundle_macos / target.name

    for subdir in bundle_subdirs:
        subdir.mkdir(exist_ok=True, parents=True)

    shutil.copy(target, bundle_executable)

    with open(bundle_info_plist, "w", encoding="utf-8") as fopen:
        fopen.write(
            INFO_PLIST_TMPL.format(
                executable=target.name,
                bundle_name=target.stem,
                bundle_identifier=f"{prefix}.{target.stem}",
                bundle_version=version,
                versioned_bundle_name=f"{target.stem} {version}",
            )
        )

    with open(bundle_pkg_info, "w", encoding="utf-8") as fopen:
        fopen.write("APPL????")

    oldmode = os.stat(bundle_executable).st_mode
    os.chmod(bundle_executable, oldmode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if add_to_resources:
        bundle_resources.mkdir(exist_ok=True, parents=True)
        for resource in add_to_resources:
            resource = Path(resource)
            shutil.copytree(resource, bundle_resources / resource.name)

    macho_standalone.standaloneApp(bundle)


def get_dependencies(target: str, names: dict[str, Set] = None, deps: list[str] = None):
    """get dependencies in tree structure and as a list of paths"""
    key = os.path.basename(target)
    _deps = [] if not deps else deps
    _names = {} if not names else names
    _names[key] = set()
    result = subprocess.check_output(["otool", "-L", target], text=True)
    entries = [line.strip() for line in result.splitlines()]
    for entry in entries:
        match = re.match(r"\s*(\S+)\s*\(compatibility version .+\)$", entry)
        if match:
            path = match.group(1)
            dep_path, dep_filename = os.path.split(path)
            if any(dep_path.startswith(p) for p in PATTERNS) or dep_path == "":
                item = (path, "@rpath/" + dep_filename)
                _names[key].add(item)
                if path not in _deps:
                    _deps.append(path)
                    get_dependencies(path, _names, _deps)
    return _names, _deps



if __name__ == "__main__":
    tree, dependencies = get_dependencies('libguile-3.0.1.dylib')
