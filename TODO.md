# macbundler TODO

Remaining tasks extracted from PROJECT_REVIEW.md.

## High Priority

### Features
- [ ] **Framework bundling support** - Currently skipped with `if ".framework" in line: continue`. Significant limitation for apps using Qt, SDL, etc. (High effort, Deferred)

### Testing
- [x] Test `Dependency._get_user_input_dir_for_file()` interactive prompt
- [x] Test ARM Mac signing workaround path
- [x] Test notarization failure handling
- [x] Test edge cases (symlink cycles, unicode paths, etc.)

## Medium Priority

### Features
- [x] **Icon handling** - Add CLI option to specify or generate icons
- [x] **Progress indicators** - Show spinner/progress for notarization waits
- [x] **Expand Info.plist template** - Add common keys like `LSMinimumSystemVersion`, `NSHighResolutionCapable`
- [x] **Add dry-run to all commands** - Now all commands (create, fix, sign, package) have dry-run
- [x] **Universal binary support** - Explicit handling for fat/universal binaries (x86_64 + arm64)

### Security
- [x] **File validation** - Validate files before copying to bundle
- [x] **Certificate validation** - Validate Developer ID string format

### Documentation
- [ ] Add CONTRIBUTING.md
- [ ] Add API reference documentation
- [ ] Add architecture documentation
- [ ] Improve changelog entries (more descriptive)

## Low Priority

### Architecture
- [ ] **Split into package structure** - When module exceeds ~3000 lines:
  ```
  macbundler/
      __init__.py      # Re-exports all public API
      core.py          # Bundle, BundleFolder
      dylib.py         # DylibBundler, Dependency
      signing.py       # Codesigner
      packaging.py     # Packager
      cli.py           # CLI handlers
      errors.py        # Exception hierarchy
      logging.py       # CustomFormatter, setup_logging
  ```

### Features
- [ ] **Async support** - Parallel dependency processing
- [ ] **Plugin architecture** - Custom bundling steps
- [ ] **GUI wrapper** - Simple tkinter or native macOS GUI
