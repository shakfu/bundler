# macbundler

A Python toolkit for creating self-contained macOS application bundles with properly configured dynamic library dependencies.

## Features

- Create complete `.app` bundles from executables
- Bundle dynamic libraries (dylibs) with correct install names
- Handle rpath, @executable_path, and @loader_path resolution
- Recursive dependency collection
- Ad-hoc code signing support
- Recursive bundle signing with Developer ID support
- Full DMG packaging and signing workflow
- Both CLI and programmatic APIs

## Installation

```bash
# Using uv
uv add macbundler

# Using pip
pip install macbundler
```

## Quick Start

### Command Line

```bash
# Create a new .app bundle from an executable
macbundler create myapp

# Bundle dylibs for an existing app
macbundler fix My.app/Contents/MacOS/main -d My.app/Contents/libs/

# Sign a bundle with Developer ID
macbundler sign MyApp.app -i "John Doe"

# Create a signed and notarized DMG
macbundler package MyApp.app -i "John Doe" -k AC_PROFILE
```

### Python API

```python
from macbundler import Bundle, make_bundle

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

The CLI has four subcommands: `create`, `fix`, `sign`, and `package`.

### `macbundler create`

Create a new macOS .app bundle from an executable.

```
macbundler create <executable> [options]

Options:
  -v, --version VERSION   Bundle version (default: 1.0)
  -i, --id ID             Bundle identifier prefix (default: org.me)
  -e, --extension EXT     Bundle extension (default: .app)
  -r, --resource PATH     Add resource to bundle (repeatable)
  --no-sign               Disable ad-hoc codesigning
  --verbose               Enable debug logging
  --no-color              Disable colored output
```

**Examples:**

```bash
macbundler create myapp
macbundler create myapp --version 2.0 --id com.example.myapp
macbundler create myapp -e .plugin
macbundler create myapp -r ./resources -r ./data
```

### `macbundler fix`

Bundle dynamic libraries and fix paths in existing files.

```
macbundler fix <files...> -d <dest> [options]

Options:
  -d, --dest DIR          Destination for bundled libraries (required)
  -p, --prefix PATH       Library path prefix (default: @executable_path/../libs/)
  -s, --search DIR        Additional search path (repeatable)
  -x, --exclude DIR       Exclude libraries from directory (repeatable)
  -f, --force             Overwrite destination directory
  --no-sign               Disable ad-hoc codesigning
  --verbose               Enable debug logging
  --no-color              Disable colored output
```

**Examples:**

```bash
macbundler fix My.app/Contents/MacOS/main -d My.app/Contents/libs/
macbundler fix main -d ./libs/ -s /opt/local/lib
macbundler fix main plugin.so -d ./libs/ --force
macbundler fix main -d ./libs/ -x /opt/local/lib
```

### `macbundler sign`

Recursively codesign a macOS bundle with Developer ID.

```
macbundler sign <bundle> [options]

Options:
  -i, --dev-id ID         Developer ID name (or set DEV_ID env var)
  -e, --entitlements FILE Path to entitlements.plist
  --dry-run               Show what would be signed without signing
  --no-verify             Skip signature verification
  --verbose               Enable debug logging
  --no-color              Disable colored output
```

**Examples:**

```bash
macbundler sign MyApp.app
macbundler sign MyApp.app -i "John Doe" -e entitlements.plist
macbundler sign MyApp.app --dry-run
```

### `macbundler package`

Create a DMG, sign it, notarize with Apple, and staple the ticket.

```
macbundler package <source> [options]

Options:
  -o, --output FILE           Output DMG path (default: <source>.dmg)
  -n, --name NAME             Volume name (default: source name)
  -i, --dev-id ID             Developer ID name (or set DEV_ID env var)
  -k, --keychain-profile NAME Keychain profile for notarytool (or set KEYCHAIN_PROFILE env var)
  -e, --entitlements FILE     Path to entitlements.plist
  --no-sign                   Skip signing bundle contents
  --no-notarize               Skip notarization
  --no-staple                 Skip stapling
  --dry-run                   Show commands without executing
  --verbose                   Enable debug logging
  --no-color                  Disable colored output
```

**Examples:**

```bash
macbundler package MyApp.app
macbundler package MyApp.app -o releases/MyApp-1.0.dmg
macbundler package MyApp.app -i "John Doe" -k AC_PROFILE
macbundler package dist/ --no-notarize
```

## Python API Reference

### Bundle

Creates a complete macOS `.app` bundle structure.

```python
from macbundler import Bundle

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
from macbundler import DylibBundler
from pathlib import Path

dylib_bundler = DylibBundler(
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
for file in dylib_bundler.files_to_fix:
    dylib_bundler.collect_dependencies(file)
dylib_bundler.collect_sub_dependencies()
dylib_bundler.process_collected_deps()
```

### make_bundle

Convenience function for simple bundle creation.

```python
from macbundler import make_bundle

bundle_path = make_bundle(
    target="/path/to/myapp",
    version="1.0",
    add_to_resources=["/path/to/data"],
    base_id="com.example",
)
```

### Codesigner

Recursively codesign a macOS bundle with Developer ID support. Signs internal binaries first, then nested apps, frameworks, and finally the main bundle with runtime hardening.

```python
from macbundler import Codesigner

signer = Codesigner(
    path="MyApp.app",              # Path to bundle (.app, .bundle, .framework, .mxo)
    dev_id="John Doe",             # Developer ID name (None or "-" for ad-hoc)
    entitlements="entitlements.plist",  # Optional entitlements file
    dry_run=False,                 # If True, only show what would be signed
    verify=True,                   # Verify signatures after signing
)

# Execute the signing workflow
signer.process()

# Or preview without signing
signer.process_dry_run()
```

Environment variable `DEV_ID` can be used as fallback for the developer ID.

### Packager

Full release workflow: sign contents, create DMG, sign DMG, notarize, and staple.

```python
from macbundler import Packager

packager = Packager(
    source="MyApp.app",            # Bundle or folder to package
    output="MyApp-1.0.dmg",        # Output DMG path (default: <source>.dmg)
    volume_name="MyApp",           # Volume name (default: source name)
    dev_id="John Doe",             # Developer ID name
    keychain_profile="AC_PROFILE", # Keychain profile for notarytool
    entitlements="entitlements.plist",  # Optional entitlements file
    dry_run=False,                 # Show commands without executing
    sign_contents=True,            # Sign bundle contents before packaging
)

# Execute full workflow (sign, create DMG, sign DMG, notarize, staple)
dmg_path = packager.process()

# Or skip notarization/stapling
dmg_path = packager.process(notarize=False, staple=False)
```

Environment variables `DEV_ID` and `KEYCHAIN_PROFILE` can be used as fallbacks.

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
