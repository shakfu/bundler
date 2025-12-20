# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.3]

### Added

- **Configuration file support**
  - New `.macbundler.toml` configuration file support
  - Settings can be configured per-project instead of CLI arguments
  - Supports all subcommand options: create, sign, package

- **Icon handling**
  - New `--icon` CLI option for `create` command
  - New `icon` parameter for `Bundle` class
  - Icons are copied to Resources folder and referenced in Info.plist
  - Configurable via `.macbundler.toml`: `icon = "path/to/icon.icns"`

- **Progress indicators**
  - New `ProgressSpinner` class for terminal progress indication
  - Automatically shown during notarization (can take several minutes)
  - Uses ASCII spinner characters for terminal compatibility
  - Context manager support: `with ProgressSpinner("message"):`

- **Expanded Info.plist template**
  - Added `LSMinimumSystemVersion` key (default: "10.13")
  - Added `NSHighResolutionCapable` key (always enabled)
  - New `--min-system-version` CLI option for `create` command
  - Configurable via `.macbundler.toml`: `min_system_version = "11.0"`

- **Dry-run for all commands**
  - Added `--dry-run` to `create` command
  - Added `--dry-run` to `fix` command
  - All 4 subcommands now support dry-run: create, fix, sign, package

- **Universal binary detection**
  - New `get_binary_architectures(path)` function - returns list of architectures
  - New `is_universal_binary(path)` function - checks if binary is fat/universal
  - New `get_binary_info(path)` function - returns detailed architecture info
  - Architecture info is logged when creating bundles

- **Security validation**
  - New `validate_file()` function for file validation before bundling
  - New `validate_developer_id()` function for Developer ID format validation
  - New `is_valid_macho()` function for Mach-O binary detection
  - New `ValidationError` exception class
  - Files are validated before copying (existence, size, Mach-O format)
  - Developer IDs are validated in Codesigner and Packager classes
  - Constants for Mach-O magic numbers (`MACHO_MAGIC_NUMBERS`)

- **New tests**
  - 25 new tests for new features in `tests/test_new_features.py`
  - 35 new tests for security validation in `tests/test_security.py`
  - Total test count: 205 (up from 145)

### Changed

- `Bundle` class now accepts `icon`, `min_system_version`, and `dry_run` parameters
- `DylibBundler` class now accepts `dry_run` parameter
- `make_bundle()` function now accepts `icon`, `min_system_version`, and `dry_run` parameters

### Fixed

- **Security: shell=True removed from all subprocess calls**
  - All `subprocess.run()` calls now use `shell=False` with list arguments
  - Eliminates shell injection vulnerabilities
  - Consolidated command execution into shared `run_command()` utility

- **Error handling: sys.exit() replaced with exceptions**
  - Library code no longer calls `sys.exit()` directly
  - All errors now raise appropriate exception types
  - `sys.exit()` reserved for CLI handlers only

### Improved

- **Code organization**
  - Refactored `Dependency.__init__` into focused methods: `_resolve_path()`, `_check_should_bundle()`, `_locate_library()`
  - Consolidated duplicate `run_command()` implementations into shared utility
  - Extracted magic numbers/strings into named constants

- **Type safety**
  - Enabled strict mypy with `disallow_untyped_defs = true`
  - Complete type annotations for all functions and methods

- **Test coverage**
  - Added comprehensive CLI tests (`tests/test_cli.py`)
  - Added edge case tests (`tests/test_edge_cases.py`)
  - Tests for interactive prompts, ARM signing workaround, notarization failures

## [0.2.2]

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

## [0.2.1]

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
