# bundler

A Python toolkit for creating self-contained macOS application bundles with properly configured dynamic library dependencies.

## Features

- Create complete `.app` bundles from executables
- Bundle dynamic libraries (dylibs) with correct install names
- Handle rpath, @executable_path, and @loader_path resolution
- Recursive dependency collection
- Ad-hoc code signing support
- Both CLI and programmatic APIs

## Installation

```bash
# Using uv
uv add bundler

# Using pip
pip install bundler
```

## Quick Start

### Command Line

```bash
# Create a new .app bundle from an executable
bundler --create-bundle /path/to/myapp

# Bundle dylibs for an existing app
bundler -od -cd -d My.app/Contents/libs/ My.app/Contents/MacOS/main
```

### Python API

```python
from bundler import Bundle, make_bundle

# High-level: create bundle with one call
bundle_path = make_bundle("/path/to/myapp", version="1.0")

# Or use the Bundle class for more control
bundle = Bundle(
    "/path/to/myapp",
    version="2.0",
    base_id="com.example",
    add_to_resources=["/path/to/resources"],
)
bundle.create()
```

## CLI Reference

```
usage: bundler [-h] [-d DEST_DIR] [-p INSTALL_PATH] [-s SEARCH_PATH] [-od]
               [-cd] [-ns] [-i IGNORE] [-dm] [-nc] [-b] [-v VERSION]
               [--base-id BASE_ID] [-r RESOURCE]
               target [target ...]

bundler is a utility for creating macOS app bundles and bundling dynamic
libraries inside them.

positional arguments:
  target                file to fix (executable or app plug-in)

options:
  -h, --help            show this help message and exit
  -d, --dest-dir DEST_DIR
                        directory to send bundled libraries (relative to cwd)
  -p, --install-path INSTALL_PATH
                        'inner' path of bundled libraries (usually relative to
                        executable)
  -s, --search-path SEARCH_PATH
                        directory to add to list of locations searched (can be
                        repeated)
  -od, --overwrite-dir  overwrite output directory if it already exists.
                        implies --create-dir
  -cd, --create-dir     creates output directory if necessary
  -ns, --no-codesign    disables ad-hoc codesigning
  -i, --ignore IGNORE   ignore libraries in this directory (can be repeated)
  -dm, --debug-mode     enable debug mode
  -nc, --no-color       disable color in logging

Bundle creation options:
  -b, --create-bundle   create a new .app bundle from the target executable
  -v, --version VERSION bundle version (for --create-bundle)
  --base-id BASE_ID     bundle identifier prefix (for --create-bundle)
  -r, --resource RESOURCE
                        add resource to bundle (can be repeated)
```

### Examples

```bash
# Create a bundle with custom version and identifier
bundler -b -v 2.0 --base-id com.mycompany /path/to/myapp

# Bundle dylibs with additional search paths
bundler -od -cd -s /opt/local/lib -s /usr/local/lib \
    -d My.app/Contents/libs/ My.app/Contents/MacOS/main

# Ignore system libraries in specific directories
bundler -od -cd -i /opt/local/lib \
    -d My.app/Contents/libs/ My.app/Contents/MacOS/main
```

## Python API Reference

### Bundle

Creates a complete macOS `.app` bundle structure.

```python
from bundler import Bundle

bundle = Bundle(
    target="/path/to/executable",  # Path to the executable
    version="1.0",                  # Bundle version string
    add_to_resources=None,          # List of paths to add to Resources/
    base_id="org.me",               # Bundle identifier prefix
    extension=".app",               # Bundle extension
    codesign=True,                  # Apply ad-hoc code signing
)

# Create the bundle
bundle_path = bundle.create()
```

### DylibBundler

Low-level control over dynamic library bundling.

```python
from bundler import DylibBundler
from pathlib import Path

bundler = DylibBundler(
    dest_dir=Path("./libs/"),
    overwrite_dir=True,
    create_dir=True,
    codesign=True,
    inside_lib_path="@executable_path/../libs/",
    files_to_fix=[Path("my_executable")],
    prefixes_to_ignore=[Path("/opt/local/lib")],
    search_paths=[Path("/usr/local/lib")],
)

# Collect and process dependencies
for file in bundler.files_to_fix:
    bundler.collect_dependencies(file)
bundler.collect_sub_dependencies()
bundler.process_collected_deps()
```

### make_bundle

Convenience function for simple bundle creation.

```python
from bundler import make_bundle

bundle_path = make_bundle(
    target="/path/to/myapp",
    version="1.0",
    add_to_resources=["/path/to/data"],
    base_id="com.example",
)
```

## Bundle Structure

The created `.app` bundle follows the standard macOS structure:

```
MyApp.app/
    Contents/
        Info.plist      # Bundle metadata
        PkgInfo         # Package type identifier
        MacOS/
            myapp       # Main executable
        libs/           # Bundled dynamic libraries
            libfoo.dylib
            libbar.dylib
        Resources/      # Optional resources
            data/
        Frameworks/     # Optional frameworks
```

## How It Works

1. **Dependency Collection**: Uses `otool -l` to analyze Mach-O binaries and extract LC_LOAD_DYLIB and LC_RPATH entries.

2. **Path Resolution**: Resolves @rpath, @loader_path, and @executable_path references to find actual library locations.

3. **Library Copying**: Copies non-system libraries to the bundle's libs directory.

4. **Install Name Modification**: Uses `install_name_tool` to update library paths to use @executable_path-relative paths.

5. **Code Signing**: Applies ad-hoc signatures to modified binaries (required for ARM Macs).

## Credits

The dylib bundling functionality is based on [macdylibbundler](https://github.com/auriamg/macdylibbundler) by Marianne Gagnon.

## Links

- [Apple Bundle Programming Guide](https://developer.apple.com/library/archive/documentation/CoreFoundation/Conceptual/CFBundles/BundleTypes/BundleTypes.html)
- [How to create a mac application bundle](https://stackoverflow.com/questions/7404792/how-to-create-mac-application-bundle-for-python-script-via-python)
- [Converting a commandline app to a bundle](https://stackoverflow.com/questions/33302266/is-it-possible-to-convert-a-command-line-application-to-an-application-bundle-un)
- [BundleBuilder](https://wiki.python.org/moin/BundleBuilder)
- [mgmacbundle](https://github.com/educrod/mgmacbundle)
- [macdylibbundler](https://github.com/auriamg/macdylibbundler)

## License

See [LICENSE](LICENSE) for details.
