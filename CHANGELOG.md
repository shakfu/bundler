# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.2]

- Re-release 0.2.2 to correct wrong version being pushed earlier. This version is same as 0.1.2

## [0.1.2]

### Added

- **New Codesigner**
  - Recursive bundle signing with Developer ID support
  - Proper signing order: internal binaries -> apps -> frameworks -> main runtime
  - Entitlements and hardened runtime support
  - Dry-run mode for testing
  - Signature verification
  - Environment variable support (DEV_ID)
  - New subcmd: `macbundler sign <bundle> [-i DEV_ID] [-e ENTITLEMENTS] [--dry-run]`

- **New Packager**
  - Full DMG packaging workflow
  - Signs bundle contents with Codesigner
  - Creates DMG with hdiutil
  - Signs DMG with Developer ID
  - Notarizes with xcrun notarytool
  - Staples with xcrun stapler
  - Environment variable support (DEV_ID, KEYCHAIN_PROFILE)
  - New subcmd: `macbundler package <source> [-o OUTPUT] [-i DEV_ID] [-k KEYCHAIN_PROFILE] [--no-notarize]`

### Changed

- **BREAKING**: Renamed project from `bundler` to `macbundler`
  - Package name: `bundler` -> `macbundler`
  - Module file: `bundler.py` -> `macbundler.py`
  - CLI command: `bundler` -> `macbundler`
  - Python imports: `from bundler import ...` -> `from macbundler import ...`

## [0.1.1]

### Changed

- **BREAKING**: Merged `macbundler.py` and `dylibbundler.py` into a single unified module
- **BREAKING**: Redesigned CLI with subcommands (`macbundler create`, `macbundler fix`)
- `Bundle.create_frameworks()` renamed to `Bundle.bundle_dependencies()`
- `Bundle.bundle_dependencies()` now uses `DylibBundler` instead of `macholib.macho_standalone`
- Removed `macholib` dependency - the module is now dependency-free

### Added

- `macbundler create` subcommand for creating .app bundles
- `macbundler fix` subcommand for fixing dylib paths in existing files
- `-e/--extension` option to set bundle suffix (default: `.app`)
- `-f/--force` option to overwrite destination directory
- `--verbose` option for debug logging
- `Bundle` class now accepts `codesign` parameter to control ad-hoc signing
- CLI entry point `macbundler` via `pyproject.toml` scripts
- Makefile with full development workflow (test, lint, format, typecheck, build, publish)
- Integration tests with real compiled executables and dylib dependencies
- Comprehensive test suite (38 tests: unit + integration)
- Full API documentation in README.md
- Dev dependencies: ruff, mypy, pytest-cov, twine
- Tool configurations in pyproject.toml for ruff, mypy, and coverage

### Removed

- `dylibbundler.py` - functionality merged into `macbundler.py`
- `DependencyTree` class - replaced by `DylibBundler`
- `get_dependencies()` function - use `DylibBundler.collect_dependencies()` instead
- `macholib` dependency
- Old CLI flags: `-b`, `-od`, `-cd`, `-dm`, `-nc`, `-ns`, `--base-id`

### Fixed

- CLI now properly supports repeatable options (`-s`, `-x`, `-r`)
- Improved error handling with dedicated exception classes
- Exception chaining with `raise ... from` for better tracebacks

## [0.1.0]

### Added

- Initial release
- `macbundler.py` - High-level bundle creation using macholib
- `dylibbundler.py` - Low-level dylib bundling (port of macdylibbundler)
- `Bundle` class for creating macOS .app bundles
- `BundleFolder` class for managing bundle directories
- `DylibBundler` class for bundling dynamic libraries
- `Dependency` class for handling individual library dependencies
- `make_bundle()` convenience function
- Support for rpath, @executable_path, and @loader_path resolution
- Ad-hoc code signing for ARM Mac compatibility
- Color-coded logging with timestamps
