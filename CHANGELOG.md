# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0]

### Changed

- **BREAKING**: Merged `bundler.py` and `dylibbundler.py` into a single unified module
- **BREAKING**: Redesigned CLI with subcommands (`bundler create`, `bundler fix`)
- `Bundle.create_frameworks()` renamed to `Bundle.bundle_dependencies()`
- `Bundle.bundle_dependencies()` now uses `DylibBundler` instead of `macholib.macho_standalone`
- Removed `macholib` dependency - the module is now dependency-free

### Added

- `bundler create` subcommand for creating .app bundles
- `bundler fix` subcommand for fixing dylib paths in existing files
- `-e/--extension` option to set bundle suffix (default: `.app`)
- `-f/--force` option to overwrite destination directory
- `--verbose` option for debug logging
- `Bundle` class now accepts `codesign` parameter to control ad-hoc signing
- CLI entry point `bundler` via `pyproject.toml` scripts
- Makefile with full development workflow (test, lint, format, typecheck, build, publish)
- Integration tests with real compiled executables and dylib dependencies
- Comprehensive test suite (38 tests: unit + integration)
- Full API documentation in README.md
- Dev dependencies: ruff, mypy, pytest-cov, twine
- Tool configurations in pyproject.toml for ruff, mypy, and coverage

### Removed

- `dylibbundler.py` - functionality merged into `bundler.py`
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
- `bundler.py` - High-level bundle creation using macholib
- `dylibbundler.py` - Low-level dylib bundling (port of macdylibbundler)
- `Bundle` class for creating macOS .app bundles
- `BundleFolder` class for managing bundle directories
- `DylibBundler` class for bundling dynamic libraries
- `Dependency` class for handling individual library dependencies
- `make_bundle()` convenience function
- Support for rpath, @executable_path, and @loader_path resolution
- Ad-hoc code signing for ARM Mac compatibility
- Color-coded logging with timestamps
