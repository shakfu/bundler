#!/usr/bin/env python3
"""macbundler - macOS application bundler and dynamic library bundler.

This module provides tools for:
1. Creating macOS .app bundles with proper structure
2. Bundling dynamic libraries inside macOS app bundles

It combines high-level bundle creation with low-level dylib bundling,
providing both programmatic APIs and a command-line interface.

The dylib bundling functionality is a Python translation of the C++
macdylibbundler utility by Marianne Gagnon:
https://github.com/auriamg/macdylibbundler

Usage (CLI):
    # Bundle dylibs for an existing executable
    macbundler -od -cd -d My.app/Contents/libs/ My.app/Contents/MacOS/main

    # Create a new .app bundle from an executable
    macbundler --create-bundle /path/to/executable

Usage (API):
    from macbundler import Bundle, DylibBundler, make_bundle

    # High-level: create bundle with dependencies
    bundle = Bundle("/path/to/executable")
    bundle.create()

    # Low-level: bundle dylibs manually
    dylib_bundler = DylibBundler(
        dest_dir="./libs/",
        files_to_fix=["my_executable"],
        create_dir=True
    )
    dylib_bundler.collect_dependencies(Path("my_executable"))
    dylib_bundler.collect_sub_dependencies()
    dylib_bundler.process_collected_deps()
"""

import argparse
import datetime
import itertools
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# ----------------------------------------------------------------------------
# Constants

__version__ = "0.2.3"

# Type aliases
Pathlike = Path | str

# Warning message for uncertain dependency handling
CAVEAT = (
    "MAY NOT CORRECTLY HANDLE THIS DEPENDENCY: "
    "Manually check the executable with 'otool -L'"
)

# Bundle package type identifier (APPL = Application, ???? = creator code)
PKG_INFO_CONTENT = "APPL????"

# Default install path prefix for bundled libraries
DEFAULT_LIB_PATH = "@executable_path/../libs/"

# Default bundle identifier prefix
DEFAULT_BUNDLE_ID = "org.me"

# Default bundle extension
DEFAULT_BUNDLE_EXT = ".app"

# Environment variable names
ENV_DEV_ID = "DEV_ID"
ENV_KEYCHAIN_PROFILE = "KEYCHAIN_PROFILE"

# File extensions for code signing
SIGNABLE_FILE_EXTENSIONS = [".so", ".dylib"]
SIGNABLE_FOLDER_EXTENSIONS = [".mxo", ".framework", ".app", ".bundle"]

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
    <string>{icon_file}</string>
    <key>CFBundleIdentifier</key>
    <string>{bundle_identifier}</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>{bundle_name}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>{bundle_version}</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleVersion</key>
    <string>{bundle_version}</string>
    <key>LSMinimumSystemVersion</key>
    <string>{min_system_version}</string>
    <key>NSAppleScriptEnabled</key>
    <string>YES</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSMainNibFile</key>
    <string>MainMenu</string>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>
"""

# Default minimum macOS version
DEFAULT_MIN_SYSTEM_VERSION = "10.13"

ENTITLEMENTS_PLIST_TMPL = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-jit</key>
    <false/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <false/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
    <key>com.apple.security.cs.allow-dyld-environment-variables</key>
    <true/>
</dict>
</plist>
"""

# ----------------------------------------------------------------------------
# Optional dotenv support (zero production dependencies)


def _load_dotenv() -> None:
    """Attempt to load .env file if python-dotenv is available."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


_load_dotenv()

# ----------------------------------------------------------------------------
# Configuration file support


def load_config(config_path: Path | None = None) -> dict[str, object]:
    """Load configuration from a TOML file.

    Searches for configuration in the following order:
    1. Explicit config_path if provided
    2. .macbundler.toml in current directory
    3. macbundler.toml in current directory

    Note: pyproject.toml is intentionally NOT searched because config
    may contain sensitive credentials (DEV_ID, KEYCHAIN_PROFILE) that
    should not be committed to version control.

    Args:
        config_path: Optional explicit path to config file

    Returns:
        Configuration dictionary (empty if no config found)

    Example .macbundler.toml:
        [create]
        version = "2.0"
        id = "com.example"
        extension = ".app"

        [sign]
        dev_id = "John Doe"
        entitlements = "entitlements.plist"

        [package]
        dev_id = "John Doe"
        keychain_profile = "AC_PROFILE"
    """
    # Try to import tomllib (Python 3.11+) or tomli as fallback
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found]
        except ImportError:
            return {}

    # Determine config file path
    if config_path and config_path.exists():
        paths_to_try = [config_path]
    else:
        cwd = Path.cwd()
        paths_to_try = [
            cwd / ".macbundler.toml",
            cwd / "macbundler.toml",
        ]

    for path in paths_to_try:
        if path.exists():
            try:
                with open(path, "rb") as f:
                    data: dict[str, object] = tomllib.load(f)
                return data
            except Exception:
                continue

    return {}


def get_config_value(
    config: dict[str, object],
    section: str,
    key: str,
    default: str | None = None,
) -> str | None:
    """Get a value from config with section.key lookup.

    Args:
        config: Configuration dictionary
        section: Section name (e.g., "create", "sign")
        key: Key name within section
        default: Default value if not found

    Returns:
        Configuration value or default
    """
    section_config = config.get(section, {})
    if not isinstance(section_config, dict):
        return default
    value = section_config.get(key, default)
    if value is None or isinstance(value, str):
        return value
    return default


# Global config (loaded lazily)
_config: dict[str, object] | None = None


def get_config() -> dict[str, object]:
    """Get the global configuration, loading it if necessary."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


# ----------------------------------------------------------------------------
# Error handling


class BundlerError(Exception):
    """Base exception class for macbundler errors."""


class CommandError(BundlerError):
    """Exception raised when a command fails."""

    def __init__(
        self, command: str, returncode: int, output: str | None = None
    ):
        self.command = command
        self.returncode = returncode
        self.output = output
        super().__init__(
            f"Command '{command}' failed with return code {returncode}"
        )


class FileError(BundlerError):
    """Exception raised when a file operation fails."""


class ConfigurationError(BundlerError):
    """Exception raised when configuration is invalid."""


class CodesignError(BundlerError):
    """Exception raised when codesigning fails."""


class NotarizationError(BundlerError):
    """Exception raised when notarization fails."""


class PackagingError(BundlerError):
    """Exception raised when DMG packaging fails."""


class ValidationError(BundlerError):
    """Exception raised when validation fails."""


# ----------------------------------------------------------------------------
# File and certificate validation

# Maximum file size for validation (1GB) - prevents copying unreasonably large files
MAX_FILE_SIZE = 1024 * 1024 * 1024

# Mach-O magic numbers for binary validation
MACHO_MAGIC_NUMBERS = {
    b"\xfe\xed\xfa\xce",  # MH_MAGIC (32-bit)
    b"\xce\xfa\xed\xfe",  # MH_CIGAM (32-bit, reverse byte order)
    b"\xfe\xed\xfa\xcf",  # MH_MAGIC_64 (64-bit)
    b"\xcf\xfa\xed\xfe",  # MH_CIGAM_64 (64-bit, reverse byte order)
    b"\xca\xfe\xba\xbe",  # FAT_MAGIC (universal binary)
    b"\xbe\xba\xfe\xca",  # FAT_CIGAM (universal binary, reverse byte order)
}

# Developer ID format: "Name" or "Name (TEAM_ID)" where TEAM_ID is 10 alphanumeric chars
# The full signing identity is "Developer ID Application: Name (TEAM_ID)"
DEVELOPER_ID_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9\s\.\-\,\']+(?:\s+\([A-Z0-9]{10}\))?$"
)


def validate_file(
    path: Pathlike,
    check_executable: bool = False,
    check_macho: bool = False,
    max_size: int = MAX_FILE_SIZE,
) -> None:
    """Validate a file before copying to bundle.

    Performs security checks to ensure the file is safe to bundle:
    - Exists and is a regular file (not symlink, device, socket, etc.)
    - Is readable
    - Has non-zero size
    - Is not larger than max_size
    - Optionally: is executable
    - Optionally: is a valid Mach-O binary

    Args:
        path: Path to the file to validate
        check_executable: If True, verify the file is executable
        check_macho: If True, verify the file is a valid Mach-O binary
        max_size: Maximum allowed file size in bytes

    Raises:
        ValidationError: If any validation check fails
    """
    path = Path(path)

    # Check existence
    if not path.exists():
        raise ValidationError(f"File does not exist: {path}")

    # Check it's a regular file (not symlink target, just the path itself)
    if path.is_symlink():
        raise ValidationError(f"File is a symbolic link: {path}")

    if not path.is_file():
        raise ValidationError(f"Path is not a regular file: {path}")

    # Check readability
    if not os.access(path, os.R_OK):
        raise ValidationError(f"File is not readable: {path}")

    # Check file size
    try:
        size = path.stat().st_size
    except OSError as e:
        raise ValidationError(f"Cannot stat file {path}: {e}") from e

    if size == 0:
        raise ValidationError(f"File is empty (zero bytes): {path}")

    if size > max_size:
        raise ValidationError(
            f"File exceeds maximum size ({size} > {max_size} bytes): {path}"
        )

    # Check executable permission if requested
    if check_executable and not os.access(path, os.X_OK):
        raise ValidationError(f"File is not executable: {path}")

    # Check Mach-O magic number if requested
    if check_macho:
        try:
            with open(path, "rb") as f:
                magic = f.read(4)
        except OSError as e:
            raise ValidationError(f"Cannot read file {path}: {e}") from e

        if magic not in MACHO_MAGIC_NUMBERS:
            raise ValidationError(f"File is not a valid Mach-O binary: {path}")


def validate_developer_id(dev_id: str) -> None:
    """Validate Developer ID string format.

    Developer ID should be in one of these formats:
    - "John Doe" (name only)
    - "John Doe (ABCD123456)" (name with 10-character Team ID)

    The full signing identity "Developer ID Application: ..." is constructed
    by the Codesigner class.

    Args:
        dev_id: The Developer ID name to validate

    Raises:
        ValidationError: If the Developer ID format is invalid
    """
    if not dev_id or not dev_id.strip():
        raise ValidationError("Developer ID cannot be empty")

    dev_id = dev_id.strip()

    # Check minimum length
    if len(dev_id) < 2:
        raise ValidationError(f"Developer ID is too short: '{dev_id}'")

    # Check maximum length (reasonable limit)
    if len(dev_id) > 100:
        raise ValidationError(
            f"Developer ID is too long (max 100 characters): '{dev_id}'"
        )

    # Check format with regex
    if not DEVELOPER_ID_PATTERN.match(dev_id):
        raise ValidationError(
            f"Developer ID has invalid format: '{dev_id}'. "
            "Expected format: 'Name' or 'Name (TEAM_ID)' where TEAM_ID is 10 alphanumeric characters"
        )


def is_valid_macho(path: Pathlike) -> bool:
    """Check if a file is a valid Mach-O binary.

    Args:
        path: Path to the file to check

    Returns:
        True if the file is a valid Mach-O binary, False otherwise
    """
    path = Path(path)
    if not path.exists() or not path.is_file():
        return False

    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        return magic in MACHO_MAGIC_NUMBERS
    except OSError:
        return False


# ----------------------------------------------------------------------------
# Progress indicator


class ProgressSpinner:
    """A simple terminal spinner for long-running operations.

    Uses ASCII characters for compatibility. No external dependencies.

    Example:
        with ProgressSpinner("Processing"):
            time.sleep(5)
    """

    SPINNER_CHARS = ["|", "/", "-", "\\"]

    def __init__(self, message: str = ""):
        self.message = message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _spin(self) -> None:
        """Spinner thread function."""
        spinner = itertools.cycle(self.SPINNER_CHARS)
        while not self._stop_event.is_set():
            sys.stdout.write(f"\r{self.message} {next(spinner)} ")
            sys.stdout.flush()
            time.sleep(0.1)
        # Clear the spinner line
        sys.stdout.write(f"\r{self.message} done\n")
        sys.stdout.flush()

    def start(self) -> None:
        """Start the spinner."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the spinner."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def __enter__(self) -> "ProgressSpinner":
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()


# ----------------------------------------------------------------------------
# Logging configuration


class CustomFormatter(logging.Formatter):
    """Custom logging formatting class with color support."""

    class color:
        """Text colors for terminal output."""

        white = "\x1b[97;20m"
        grey = "\x1b[38;20m"
        green = "\x1b[32;20m"
        cyan = "\x1b[36;20m"
        yellow = "\x1b[33;20m"
        red = "\x1b[31;20m"
        bold_red = "\x1b[31;1m"
        reset = "\x1b[0m"

    cfmt = (
        f"{color.white}%(delta)s{color.reset} - "
        f"{{}}%(levelname)s{color.reset} - "
        f"{color.white}%(name)s.%(funcName)s{color.reset} - "
        f"{color.grey}%(message)s{color.reset}"
    )

    FORMATS = {
        logging.DEBUG: cfmt.format(color.grey),
        logging.INFO: cfmt.format(color.green),
        logging.WARNING: cfmt.format(color.yellow),
        logging.ERROR: cfmt.format(color.red),
        logging.CRITICAL: cfmt.format(color.bold_red),
    }

    def __init__(self, use_color: bool = True):
        self.use_color = use_color
        self.fmt = (
            "%(delta)s - %(levelname)s - %(name)s.%(funcName)s - %(message)s"
        )

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with color if enabled."""
        if not self.use_color:
            log_fmt = self.fmt
        else:
            log_fmt = self.FORMATS[record.levelno]
        duration = datetime.datetime.fromtimestamp(
            record.relativeCreated / 1000, datetime.timezone.utc
        )
        record.delta = duration.strftime("%H:%M:%S")
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def setup_logging(debug: bool = True, use_color: bool = True) -> None:
    """Configure logging for the application.

    Args:
        debug: Whether to enable debug logging
        use_color: Whether to use colored output
    """
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(CustomFormatter(use_color))
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        handlers=[stream_handler],
    )


# ----------------------------------------------------------------------------
# Command execution utilities


def run_command(
    command: list[str],
    dry_run: bool = False,
    log: logging.Logger | None = None,
) -> str:
    """Run a command and return its output.

    This is the consolidated command execution utility used throughout
    the module. It provides consistent error handling and optional
    dry-run support. Uses shell=False for security.

    Args:
        command: The command as a list of arguments
        dry_run: If True, log command but don't execute (default: False)
        log: Optional logger for debug/dry-run output

    Returns:
        The command stdout output

    Raises:
        CommandError: If the command fails
    """
    cmd_str = " ".join(command)
    if log:
        log.debug("%s", cmd_str)
    if dry_run:
        if log:
            log.info("[DRY RUN] %s", cmd_str)
        return ""
    try:
        result = subprocess.run(
            command, shell=False, check=True, text=True, capture_output=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise CommandError(cmd_str, e.returncode, e.stderr or e.output) from e


# ----------------------------------------------------------------------------
# Universal binary detection


def get_binary_architectures(binary_path: Pathlike) -> list[str]:
    """Get the architectures of a Mach-O binary using lipo.

    Args:
        binary_path: Path to the binary file

    Returns:
        List of architecture strings (e.g., ["x86_64", "arm64"])
        Empty list if not a valid Mach-O binary
    """
    path = Path(binary_path)
    if not path.exists():
        return []

    try:
        result = subprocess.run(
            ["lipo", "-info", str(path)],
            check=True,
            text=True,
            capture_output=True,
        )
        # Output format: "Architectures in the fat file: /path are: x86_64 arm64"
        # or: "Non-fat file: /path is architecture: x86_64"
        output = result.stdout.strip()
        if "are:" in output:
            # Fat/universal binary
            archs_str = output.split("are:")[-1].strip()
            return archs_str.split()
        elif "is architecture:" in output:
            # Single architecture
            arch = output.split("is architecture:")[-1].strip()
            return [arch]
        return []
    except subprocess.CalledProcessError:
        return []


def is_universal_binary(binary_path: Pathlike) -> bool:
    """Check if a binary is a universal (fat) binary.

    Args:
        binary_path: Path to the binary file

    Returns:
        True if the binary contains multiple architectures
    """
    archs = get_binary_architectures(binary_path)
    return len(archs) > 1


def get_binary_info(binary_path: Pathlike) -> dict[str, object]:
    """Get detailed information about a Mach-O binary.

    Args:
        binary_path: Path to the binary file

    Returns:
        Dictionary with binary information:
        - architectures: List of architecture strings
        - is_universal: True if fat binary
        - is_arm: True if contains arm64
        - is_intel: True if contains x86_64
    """
    archs = get_binary_architectures(binary_path)
    return {
        "architectures": archs,
        "is_universal": len(archs) > 1,
        "is_arm": "arm64" in archs,
        "is_intel": "x86_64" in archs,
    }


# ----------------------------------------------------------------------------
# Bundle folder and structure classes


class BundleFolder:
    """Manages a folder within the bundle structure."""

    def __init__(self, path: Pathlike):
        """Initialize a bundle folder.

        Args:
            path: Path to the folder
        """
        self.path = Path(path)

    def create(self) -> None:
        """Create the bundle folder if it doesn't exist."""
        if not self.path.exists():
            self.path.mkdir(exist_ok=True, parents=True)
        if not self.path.is_dir():
            raise FileError(f"{self.path} is not a directory")

    def copy(self, src: Pathlike) -> None:
        """Recursively copy from src to bundle folder.

        Args:
            src: Source path to copy from
        """
        src = Path(src)
        shutil.copytree(src, self.path / src.name)


class Bundle:
    """Creates a macOS application bundle.

    This class handles the creation of a proper macOS .app bundle structure
    including Info.plist, PkgInfo, and framework/library bundling.

    Args:
        target: Path to the target executable
        version: Bundle version string (default: "1.0")
        add_to_resources: List of paths to add to Resources folder
        base_id: Bundle identifier prefix (default: DEFAULT_BUNDLE_ID)
        extension: Bundle extension (default: DEFAULT_BUNDLE_EXT)
        codesign: Whether to apply ad-hoc code signing (default: True)
        icon: Path to icon file (.icns) to include in bundle
        min_system_version: Minimum macOS version (default: "10.13")
        dry_run: If True, only show what would be done without doing it

    Example:
        bundle = Bundle("/path/to/myapp")
        bundle.create()
    """

    def __init__(
        self,
        target: Pathlike,
        version: str = "1.0",
        add_to_resources: list[str] | None = None,
        base_id: str = DEFAULT_BUNDLE_ID,
        extension: str = DEFAULT_BUNDLE_EXT,
        codesign: bool = True,
        icon: Pathlike | None = None,
        min_system_version: str = DEFAULT_MIN_SYSTEM_VERSION,
        dry_run: bool = False,
    ):
        self.target = Path(target)
        self.version = version
        self.add_to_resources = add_to_resources
        self.base_id = base_id
        self.extension = extension
        self.codesign = codesign
        self.icon = Path(icon) if icon else None
        self.min_system_version = min_system_version
        self.dry_run = dry_run
        self.log = logging.getLogger(self.__class__.__name__)

        # Bundle structure paths
        self.bundle = self.target.parent / (self.target.stem + extension)
        self.contents = self.bundle / "Contents"
        self.macos = self.contents / "MacOS"
        self.libs = self.contents / "libs"

        # Special bundle folders
        self.frameworks = BundleFolder(self.contents / "Frameworks")
        self.resources = BundleFolder(self.contents / "Resources")

        # Files
        self.info_plist = self.contents / "Info.plist"
        self.pkg_info = self.contents / "PkgInfo"
        self.executable = self.macos / self.target.name

        # Icon file name in bundle
        self._icon_filename = self.icon.name if self.icon else "app.icns"

    def create_executable(self) -> None:
        """Copy target to bundle and set executable permissions."""
        # Validate target executable before copying
        validate_file(self.target, check_executable=True, check_macho=True)

        # Log architecture information for the target executable
        archs = get_binary_architectures(self.target)
        if archs:
            arch_info = ", ".join(archs)
            if len(archs) > 1:
                self.log.info("Target is universal binary: %s", arch_info)
            else:
                self.log.info("Target architecture: %s", arch_info)

        if self.dry_run:
            self.log.info(
                "[DRY RUN] Would copy %s to %s", self.target, self.executable
            )
            return
        shutil.copy(self.target, self.executable)
        oldmode = os.stat(self.executable).st_mode
        os.chmod(
            self.executable,
            oldmode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
        )

    def create_info_plist(self) -> None:
        """Create the Info.plist file."""
        content = INFO_PLIST_TMPL.format(
            executable=self.target.name,
            bundle_name=self.target.stem,
            bundle_identifier=f"{self.base_id}.{self.target.stem}",
            bundle_version=self.version,
            versioned_bundle_name=f"{self.target.stem} {self.version}",
            icon_file=self._icon_filename,
            min_system_version=self.min_system_version,
        )
        if self.dry_run:
            self.log.info("[DRY RUN] Would create %s", self.info_plist)
            return
        with open(self.info_plist, "w", encoding="utf-8") as fopen:
            fopen.write(content)

    def create_pkg_info(self) -> None:
        """Create the PkgInfo file."""
        if self.dry_run:
            self.log.info("[DRY RUN] Would create %s", self.pkg_info)
            return
        with open(self.pkg_info, "w", encoding="utf-8") as fopen:
            fopen.write(PKG_INFO_CONTENT)

    def create_resources(self) -> None:
        """Create and populate the Resources folder."""
        # Validate icon file if specified
        if self.icon:
            validate_file(self.icon)

        # Validate resource files/directories
        if self.add_to_resources:
            for resource in self.add_to_resources:
                resource_path = Path(resource)
                if not resource_path.exists():
                    raise ValidationError(
                        f"Resource does not exist: {resource}"
                    )

        if self.dry_run:
            if self.add_to_resources:
                for resource in self.add_to_resources:
                    self.log.info(
                        "[DRY RUN] Would copy %s to Resources", resource
                    )
            if self.icon:
                self.log.info(
                    "[DRY RUN] Would copy icon %s to Resources", self.icon
                )
            return

        # Create Resources folder if we have resources or an icon
        if self.add_to_resources or self.icon:
            self.resources.create()

        if self.add_to_resources:
            for resource in self.add_to_resources:
                self.resources.copy(resource)

        # Copy icon to Resources folder
        if self.icon:
            dest_icon = self.resources.path / self.icon.name
            shutil.copy2(self.icon, dest_icon)
            self.log.info("Added icon: %s", self.icon.name)

    def bundle_dependencies(self) -> None:
        """Bundle dynamic libraries using DylibBundler."""
        if self.dry_run:
            self.log.info(
                "[DRY RUN] Would bundle dynamic libraries for %s",
                self.executable,
            )
            return

        self.log.info("Bundling dynamic libraries for %s", self.executable)

        bundler = DylibBundler(
            dest_dir=self.libs,
            overwrite_dir=True,
            create_dir=True,
            codesign=self.codesign,
            inside_lib_path=DEFAULT_LIB_PATH,
            files_to_fix=[self.executable],
        )

        bundler.collect_dependencies(self.executable)
        bundler.collect_sub_dependencies()
        bundler.process_collected_deps()

    def create(self) -> Path:
        """Create the complete bundle.

        Returns:
            Path to the created bundle
        """
        if self.dry_run:
            self.log.info("[DRY RUN] Would create bundle at %s", self.bundle)
        else:
            self.log.info("Creating bundle at %s", self.bundle)
            self.macos.mkdir(exist_ok=True, parents=True)

        self.create_executable()
        self.create_info_plist()
        self.create_pkg_info()
        self.create_resources()
        self.bundle_dependencies()

        if self.dry_run:
            self.log.info(
                "[DRY RUN] Bundle would be created at: %s", self.bundle
            )
        else:
            self.log.info("Bundle created successfully: %s", self.bundle)
        return self.bundle


# ----------------------------------------------------------------------------
# Dependency and DylibBundler classes


class Dependency:
    """Represents a dynamic library dependency.

    This class handles the resolution, copying, and path modification
    of a single dynamic library dependency.

    Args:
        parent: The parent DylibBundler instance
        path: The path to the dependency (may be rpath-relative)
        dependent_file: The file that depends on this dependency
    """

    def __init__(
        self, parent: "DylibBundler", path: Pathlike, dependent_file: Pathlike
    ):
        self.parent = parent
        self.filename = ""
        self.prefix = Path()
        self.symlinks: list[Path] = []
        self.new_name = ""
        self.log = logging.getLogger(self.__class__.__name__)

        path = Path(str(path).strip())
        dependent_file = Path(dependent_file)

        try:
            self._resolve_path(path, dependent_file)
            if not self._check_should_bundle():
                return
            self._locate_library()
            self.new_name = self.filename
        except FileError:
            raise
        except Exception as e:
            raise FileError(
                f"Failed to initialize dependency for {path}: {e}"
            ) from e

    def _resolve_path(self, path: Path, dependent_file: Path) -> None:
        """Resolve the dependency path and set filename/prefix.

        Args:
            path: The path to resolve (may be rpath-relative)
            dependent_file: The file that depends on this dependency

        Raises:
            FileError: If the path cannot be resolved
        """
        if self._is_rpath(path):
            original_file = self.search_filename_in_rpaths(path, dependent_file)
        else:
            try:
                original_file = path.resolve()
            except OSError as e:
                raise FileError(f"Cannot resolve path '{path}': {e}") from e

        # Track if original path was a symlink
        if original_file != path:
            self.add_symlink(path)

        self.filename = original_file.name
        self.prefix = original_file.parent

    def _check_should_bundle(self) -> bool:
        """Check if this dependency should be bundled.

        Returns:
            True if the dependency should be bundled, False otherwise
        """
        return self.parent.is_bundled_prefix(self.prefix)

    def _locate_library(self) -> None:
        """Locate the library file, searching paths or prompting user if needed.

        Raises:
            ConfigurationError: If user aborts when prompted for location
        """
        # Check if the lib is in a known location
        if self.prefix and (self.prefix / self.filename).exists():
            return

        # Initialize search paths from environment if needed
        if not self.parent.search_paths:
            self._init_search_paths()

        # Search in configured paths
        for search_path in self.parent.search_paths:
            if (search_path / self.filename).exists():
                self.log.info("FOUND %s in %s", self.filename, search_path)
                self.prefix = search_path
                return

        # If location still unknown, ask user for search path
        if not self.parent.is_ignored_prefix(self.prefix):
            self.log.warning(
                "Library %s has an incomplete name (location unknown)",
                self.filename,
            )
            self.parent.add_search_path(
                self._get_user_input_dir_for_file(self.filename)
            )

    def _get_user_input_dir_for_file(self, filename: str) -> Path:
        """Prompt user for the directory containing a file.

        Args:
            filename: The name of the file to find

        Returns:
            The directory containing the file

        Raises:
            ConfigurationError: If user aborts
        """
        for search_path in self.parent.search_paths:
            if (search_path / filename).exists():
                self.log.info(
                    "%s was found. %s", search_path / filename, CAVEAT
                )
                return search_path

        while True:
            prefix = input(
                "Please specify the directory where this library is "
                "located (or enter 'quit' to abort): "
            )

            if prefix == "quit":
                raise ConfigurationError("User aborted dependency resolution")

            prefix_path = Path(prefix)
            if not (prefix_path / filename).exists():
                self.log.info(
                    "%s does not exist. Try again", prefix_path / filename
                )
                continue

            self.log.info("%s was found. %s", prefix_path / filename, CAVEAT)
            self.parent.add_search_path(prefix_path)
            return prefix_path

    def _is_rpath(self, path: Path) -> bool:
        """Check if a path uses rpath or loader_path.

        Args:
            path: The path to check

        Returns:
            True if the path is rpath-relative
        """
        return str(path).startswith("@rpath") or str(path).startswith(
            "@loader_path"
        )

    def _init_search_paths(self) -> None:
        """Initialize search paths from environment variables."""
        search_paths: list[Pathlike] = []

        for env_var in [
            "DYLD_LIBRARY_PATH",
            "DYLD_FALLBACK_FRAMEWORK_PATH",
            "DYLD_FALLBACK_LIBRARY_PATH",
        ]:
            if env_var in os.environ:
                paths = os.environ[env_var].split(":")
                search_paths.extend(Path(p) for p in paths)

        for path in search_paths:
            self.parent.add_search_path(path)

    def _change_install_name(
        self, binary_file: Path, old_name: Pathlike, new_name: str
    ) -> None:
        """Change the install name of a dependency in a binary.

        Args:
            binary_file: The binary file to modify
            old_name: The old install name
            new_name: The new install name

        Raises:
            CommandError: If install_name_tool fails
        """
        command = [
            "install_name_tool",
            "-change",
            str(old_name),
            str(new_name),
            str(binary_file),
        ]
        try:
            self.parent.run_command(command)
        except CommandError as e:
            raise CommandError(
                f"Failed to change install name for {binary_file}: {e}",
                e.returncode,
                e.output,
            ) from e

    def _resolve_rpath(self, rpath: Path, file_prefix: Path) -> Path | None:
        """Resolve a single rpath to its full path.

        Args:
            rpath: The rpath to resolve
            file_prefix: The prefix path for @loader_path resolution

        Returns:
            The resolved path if successful, None otherwise
        """
        path_to_check = Path()
        if "@loader_path" in str(rpath):
            path_to_check = Path(
                str(rpath).replace("@loader_path/", str(file_prefix))
            )
        elif "@rpath" in str(rpath):
            path_to_check = Path(
                str(rpath).replace("@rpath/", str(file_prefix))
            )

        try:
            fullpath = path_to_check.resolve()
            self.parent.rpath_to_fullpath[rpath] = fullpath
            return fullpath
        except OSError:
            return None

    def _search_in_rpaths(
        self, rpath_file: Path, dependent_file: Path
    ) -> Path | None:
        """Search for a file in rpaths.

        Args:
            rpath_file: The rpath file to search for
            dependent_file: The file that depends on the rpath

        Returns:
            The resolved path if found, None otherwise
        """
        file_prefix = dependent_file.parent
        suffix = re.sub(r"^@[a-z_]+path/", "", str(rpath_file))

        # Check if already resolved
        if rpath_file in self.parent.rpath_to_fullpath:
            return self.parent.rpath_to_fullpath[rpath_file]

        # Try to resolve directly
        if self._resolve_rpath(rpath_file, file_prefix):
            return self.parent.rpath_to_fullpath[rpath_file]

        # Try all rpaths for the dependent file
        for rpath in self.parent.rpaths_per_file.get(dependent_file, []):
            if self._resolve_rpath(rpath / suffix, file_prefix):
                return self.parent.rpath_to_fullpath[rpath_file]

        return None

    def _search_in_search_paths(self, suffix: str) -> Path | None:
        """Search for a file in configured search paths.

        Args:
            suffix: The file suffix to search for

        Returns:
            The path if found, None otherwise
        """
        for search_path in self.parent.search_paths:
            if (search_path / suffix).exists():
                return search_path / suffix
        return None

    def search_filename_in_rpaths(
        self, rpath_file: Path, dependent_file: Path
    ) -> Path:
        """Search for a filename in rpaths.

        Args:
            rpath_file: The rpath file to search for
            dependent_file: The file that depends on the rpath

        Returns:
            The resolved path to the file
        """
        suffix = re.sub(r"^@[a-z_]+path/", "", str(rpath_file))

        # Try to find in rpaths
        fullpath = self._search_in_rpaths(rpath_file, dependent_file)
        if fullpath:
            return fullpath

        # Try to find in search paths
        fullpath = self._search_in_search_paths(suffix)
        if fullpath:
            return fullpath

        # If not found, ask user for help
        self.log.warning("can't get path for '%s'", rpath_file)
        fullpath = self._get_user_input_dir_for_file(suffix) / suffix
        return fullpath.resolve()

    def get_original_path(self) -> Path:
        """Get the original path of the dependency."""
        return self.prefix / self.filename

    def get_install_path(self) -> Path:
        """Get the destination path for the dependency."""
        return self.parent.dest_dir / self.new_name

    def get_inner_path(self) -> str:
        """Get the inner path (install name) for the dependency."""
        return f"{self.parent.inside_lib_path}{self.new_name}"

    def add_symlink(self, symlink: Path) -> None:
        """Add a symlink reference for this dependency."""
        if symlink not in self.symlinks:
            self.symlinks.append(symlink)

    def get_symlink(self, index: int) -> Path:
        """Get a symlink by index."""
        return self.symlinks[index]

    def copy_yourself(self) -> None:
        """Copy the dependency to the destination directory.

        Raises:
            CommandError: If install_name_tool fails to change identity
            ValidationError: If the library file fails validation
        """
        # Validate library file before copying
        validate_file(self.get_original_path(), check_macho=True)

        shutil.copy2(self.get_original_path(), self.get_install_path())

        # Fix the lib's inner name
        command = [
            "install_name_tool",
            "-id",
            self.get_inner_path(),
            str(self.get_install_path()),
        ]
        result = subprocess.run(command, capture_output=True)
        if result.returncode != 0:
            raise CommandError(
                f"Failed to change identity of library {self.get_install_path()}",
                result.returncode,
                result.stderr.decode() if result.stderr else None,
            )

    def fix_file_that_depends_on_me(self, file_to_fix: Path) -> None:
        """Fix dependencies in a file that depends on this library."""
        self._change_install_name(
            file_to_fix, self.get_original_path(), self.get_inner_path()
        )

        # Fix symlinks
        for symlink in self.symlinks:
            self._change_install_name(
                file_to_fix, symlink, self.get_inner_path()
            )

    def merge_if_same_as(self, other: "Dependency") -> bool:
        """Merge with another dependency if they refer to the same file.

        Args:
            other: The other dependency to compare with

        Returns:
            True if merged, False otherwise
        """
        if other.filename == self.filename:
            for symlink in self.symlinks:
                other.add_symlink(symlink)
            return True
        return False

    def print(self) -> None:
        """Print dependency information."""
        lines = [f"{self.filename} from {self.prefix}"]
        for sym in self.symlinks:
            lines.append(f"    symlink --> {sym}")
        self.log.info("\n".join(lines))


class DylibBundler:
    """Bundles dynamic libraries for macOS applications.

    This class handles the collection, copying, and path modification
    of dynamic library dependencies for macOS executables.

    Args:
        dest_dir: Directory to send bundled libraries
        overwrite_dir: Whether to overwrite existing output directory
        create_dir: Whether to create output directory if needed
        codesign: Whether to apply ad-hoc codesigning
        inside_lib_path: Inner path of bundled libraries
        files_to_fix: List of files to process
        prefixes_to_ignore: List of prefixes to ignore
        search_paths: List of search paths

    Example:
        bundler = DylibBundler(
            dest_dir="./libs/",
            files_to_fix=["my_app"],
            create_dir=True
        )
        bundler.collect_dependencies(Path("my_app"))
        bundler.collect_sub_dependencies()
        bundler.process_collected_deps()
    """

    def __init__(
        self,
        dest_dir: Pathlike = Path("./libs/"),
        overwrite_dir: bool = False,
        create_dir: bool = False,
        codesign: bool = True,
        inside_lib_path: str = DEFAULT_LIB_PATH,
        files_to_fix: list[Pathlike] | None = None,
        prefixes_to_ignore: list[Pathlike] | None = None,
        search_paths: list[Pathlike] | None = None,
        dry_run: bool = False,
    ):
        try:
            self.dest_dir = Path(dest_dir)
            self.can_overwrite_dir = overwrite_dir
            self.can_create_dir = create_dir
            self.can_codesign = codesign
            self.inside_lib_path = inside_lib_path
            self.files_to_fix = [Path(f) for f in (files_to_fix or [])]
            self.prefixes_to_ignore = [
                Path(p) for p in (prefixes_to_ignore or [])
            ]
            self.search_paths = [Path(p) for p in (search_paths or [])]
            self.dry_run = dry_run

            self.deps: list[Dependency] = []
            self.deps_per_file: dict[Path, list[Dependency]] = {}
            self.deps_collected: dict[Path, bool] = {}
            self.rpaths_per_file: dict[Path, list[Path]] = {}
            self.rpath_to_fullpath: dict[Path, Path] = {}
            self.log = logging.getLogger(self.__class__.__name__)

            # Validate configuration
            if not self.files_to_fix:
                raise ConfigurationError("No files to fix specified")
            if not self.dest_dir and not self.can_create_dir:
                raise ConfigurationError(
                    "Destination directory not specified and create_dir is False"
                )

        except Exception as e:
            raise ConfigurationError(
                f"Failed to initialize DylibBundler: {e}"
            ) from e

    def add_search_path(self, path: Pathlike) -> None:
        """Add a search path for finding libraries."""
        self.search_paths.append(Path(path))

    def search_path(self, index: int) -> Path:
        """Get a search path by index."""
        return self.search_paths[index]

    def add_file_to_fix(self, path: Pathlike) -> None:
        """Add a file to the list of files to process."""
        self.files_to_fix.append(Path(path))

    def ignore_prefix(self, prefix: Pathlike) -> None:
        """Add a prefix to the ignore list."""
        self.prefixes_to_ignore.append(Path(prefix))

    def is_system_library(self, prefix: Pathlike) -> bool:
        """Check if a prefix is a system library location."""
        prefix = str(prefix)
        return prefix.startswith("/usr/lib/") or prefix.startswith(
            "/System/Library/"
        )

    def is_ignored_prefix(self, prefix: Pathlike) -> bool:
        """Check if a prefix is in the ignore list."""
        return Path(prefix) in self.prefixes_to_ignore

    def is_bundled_prefix(self, prefix: Pathlike) -> bool:
        """Check if a prefix should be bundled."""
        prefix = str(prefix)
        if ".framework" in prefix:
            return False
        if "@executable_path" in prefix:
            return False
        if self.is_system_library(prefix):
            return False
        return not self.is_ignored_prefix(prefix)

    def run_command(self, command: list[str]) -> str:
        """Run a command and return its output.

        Args:
            command: The command as a list of arguments

        Returns:
            The command output

        Raises:
            CommandError: If the command fails
        """
        return run_command(command, dry_run=self.dry_run, log=self.log)

    def chmod(self, path: Pathlike, perm: int = 0o777) -> None:
        """Change file permissions."""
        self.log.info("change permission of %s to %s", path, perm)
        os.chmod(path, perm)

    def collect_dependencies(self, filename: Path) -> None:
        """Collect dependencies for a given file."""
        if filename in self.deps_collected:
            return

        self.collect_rpaths(filename)
        lines = self._collect_dependency_lines(filename)

        for line in lines:
            if not line.startswith("\t"):
                continue  # only lines beginning with a tab interest us
            if ".framework" in line:
                continue  # Ignore frameworks, we cannot handle them

            # trim useless info, keep only library name
            dep_path = line[1 : line.rfind(" (")]
            if self.is_system_library(dep_path):
                continue

            self.add_dependency(dep_path, filename)

        self.deps_collected[filename] = True

    def _collect_dependency_lines(self, filename: Path) -> list[str]:
        """Execute otool -l and collect dependency lines.

        Args:
            filename: Path to the Mach-O binary to analyze

        Returns:
            List of dependency lines from otool output

        Raises:
            FileError: If the file does not exist
            CommandError: If otool fails or output is malformed
        """
        if not filename.exists():
            raise FileError(
                f"Cannot find file {filename} to read its dependencies"
            )

        command = ["otool", "-l", str(filename)]
        try:
            result = subprocess.run(
                command, check=True, text=True, capture_output=True
            )
            output = result.stdout
        except subprocess.CalledProcessError as e:
            raise CommandError(
                f"Error running otool on {filename}", e.returncode
            ) from e

        lines = []
        raw_lines = output.split("\n")
        searching = False

        for line in raw_lines:
            if "cmd LC_LOAD_DYLIB" in line or "cmd LC_REEXPORT_DYLIB" in line:
                if searching:
                    raise CommandError(
                        f"Malformed otool output: failed to find name before "
                        f"next cmd in {filename}",
                        1,
                    )
                searching = True
            elif searching:
                found = line.find("name ")
                if found != -1:
                    lines.append("\t" + line[found + 5 :])
                    searching = False

        return lines

    def collect_rpaths(self, filename: Path) -> None:
        """Collect rpaths for a given file."""
        if not filename.exists():
            self.log.warning(
                "can't collect rpaths for nonexistent file '%s'", filename
            )
            return

        command = ["otool", "-l", str(filename)]
        try:
            result = subprocess.run(
                command, check=True, text=True, capture_output=True
            )
            output = result.stdout
        except subprocess.CalledProcessError:
            return

        lc_lines = output.split("\n")
        pos = 0
        read_rpath = False

        while pos < len(lc_lines):
            line = lc_lines[pos]
            pos += 1

            if read_rpath:
                start_pos = line.find("path ")
                end_pos = line.find(" (")
                if start_pos == -1 or end_pos == -1:
                    self.log.warning("Unexpected LC_RPATH format")
                    continue
                start_pos += 5
                rpath = Path(line[start_pos:end_pos])
                if filename not in self.rpaths_per_file:
                    self.rpaths_per_file[filename] = []
                self.rpaths_per_file[filename].append(rpath)
                read_rpath = False
                continue

            if "LC_RPATH" in line:
                read_rpath = True
                pos += 1

    def add_dependency(self, path: Pathlike, filename: Path) -> None:
        """Add a new dependency."""
        dep = Dependency(self, path, filename)

        # Check if this library was already added to avoid duplicates
        in_deps = False
        for existing_dep in self.deps:
            if dep.merge_if_same_as(existing_dep):
                in_deps = True
                break

        # Check if this library was already added to deps_per_file[filename]
        in_deps_per_file = False
        deps_in_file = self.deps_per_file.get(filename, [])
        for existing_dep in deps_in_file:
            if dep.merge_if_same_as(existing_dep):
                in_deps_per_file = True
                break

        if not self.is_bundled_prefix(dep.prefix):
            return

        if not in_deps:
            self.deps.append(dep)
        if not in_deps_per_file:
            self.deps_per_file[filename] = self.deps_per_file.get(
                filename, []
            ) + [dep]

    def collect_sub_dependencies(self) -> None:
        """Recursively collect each dependency's dependencies."""
        n_deps = len(self.deps)

        while True:
            n_deps = len(self.deps)
            for dep in self.deps[:n_deps]:
                original_path = dep.get_original_path()
                if dep._is_rpath(original_path):
                    original_path = dep.search_filename_in_rpaths(
                        original_path, original_path
                    )

                self.collect_dependencies(original_path)

            if len(self.deps) == n_deps:
                break  # no more dependencies were added on this iteration

    def process_collected_deps(self) -> None:
        """Process all collected dependencies."""
        for dep in self.deps:
            dep.print()

        if self.dry_run:
            self.log.info(
                "[DRY RUN] Would create destination directory: %s",
                self.dest_dir,
            )
            for dep in reversed(self.deps):
                self.log.info(
                    "[DRY RUN] Would copy %s to %s",
                    dep.get_original_path(),
                    dep.get_install_path(),
                )
            for file in reversed(self.files_to_fix):
                self.log.info("[DRY RUN] Would fix library paths in %s", file)
            return

        self.create_dest_dir()

        for dep in reversed(self.deps):
            self.log.info("Processing dependency %s", dep.get_install_path())
            dep.copy_yourself()
            self.change_lib_paths_on_file(dep.get_install_path())
            self.fix_rpaths_on_file(
                dep.get_original_path(), dep.get_install_path()
            )
            self.adhoc_codesign(dep.get_install_path())

        for file in reversed(self.files_to_fix):
            self.log.info("Processing %s", file)
            self.change_lib_paths_on_file(file)
            self.fix_rpaths_on_file(file, file)
            self.adhoc_codesign(file)

    def create_dest_dir(self) -> None:
        """Create the destination directory if needed.

        Raises:
            FileError: If directory creation fails
        """
        dest_dir = self.dest_dir
        self.log.info("Checking output directory %s", dest_dir)

        dest_exists = dest_dir.exists()

        if dest_exists and self.can_overwrite_dir:
            self.log.info("Erasing old output directory %s", dest_dir)
            try:
                shutil.rmtree(dest_dir)
            except OSError as e:
                raise FileError(
                    f"Failed to overwrite destination directory: {e}"
                ) from e
            dest_exists = False

        if not dest_exists:
            if self.can_create_dir:
                self.log.info("Creating output directory %s", dest_dir)
                try:
                    dest_dir.mkdir(parents=True)
                except OSError as e:
                    raise FileError(
                        f"Failed to create destination directory: {e}"
                    ) from e
            else:
                raise FileError(
                    "Destination directory does not exist and create_dir is False"
                )

    def change_lib_paths_on_file(self, file_to_fix: Path) -> None:
        """Change library paths in a file."""
        if file_to_fix not in self.deps_collected:
            self.collect_dependencies(file_to_fix)

        self.log.info("Fixing dependencies on %s", file_to_fix)
        deps_in_file = self.deps_per_file.get(file_to_fix, [])
        for dep in deps_in_file:
            dep.fix_file_that_depends_on_me(file_to_fix)

    def fix_rpaths_on_file(
        self, original_file: Path, file_to_fix: Path
    ) -> None:
        """Fix rpaths in a file.

        Args:
            original_file: The original file to get rpaths from
            file_to_fix: The file to modify

        Raises:
            CommandError: If install_name_tool fails to fix rpaths
        """
        rpaths_to_fix = self.rpaths_per_file.get(original_file, [])

        for rpath in rpaths_to_fix:
            command = [
                "install_name_tool",
                "-rpath",
                str(rpath),
                self.inside_lib_path,
                str(file_to_fix),
            ]
            result = subprocess.run(command, capture_output=True)
            if result.returncode != 0:
                raise CommandError(
                    f"Failed to fix rpath '{rpath}' in {file_to_fix}",
                    result.returncode,
                )

    def adhoc_codesign(self, file: Path) -> None:
        """Apply ad-hoc code signing to a file.

        Args:
            file: The file to sign

        Raises:
            CommandError: If codesigning fails on ARM
        """
        if not self.can_codesign:
            return

        self.log.info("codesign %s", file)
        sign_command = [
            "codesign",
            "--force",
            "--deep",
            "--preserve-metadata=entitlements,requirements,flags,runtime",
            "--sign",
            "-",
            str(file),
        ]

        try:
            self.run_command(sign_command)
        except CommandError:
            self.log.error(
                "An error occurred while applying ad-hoc signature to %s. Attempting workaround",
                file,
            )

            try:
                machine_output = self.run_command(["machine"])
                is_arm = "arm" in machine_output
            except CommandError:
                is_arm = False

            try:
                temp_dir = Path(tempfile.mkdtemp(prefix="macbundler."))
                temp_file = temp_dir / file.name

                # Copy file to temp location
                shutil.copy2(file, temp_file)
                # Move it back
                shutil.move(temp_file, file)
                # Remove temp dir
                shutil.rmtree(temp_dir)
                # Try signing again
                try:
                    self.run_command(sign_command)
                except CommandError as e:
                    if is_arm:
                        raise CommandError(
                            f"Failed to sign {file} on ARM: {e}",
                            e.returncode,
                            e.output,
                        ) from e
                    self.log.error(
                        "An error occurred while applying ad-hoc signature to %s",
                        file,
                    )
            except Exception as e:
                if is_arm:
                    raise CommandError(
                        f"Failed to sign {file} on ARM: {e}", 1
                    ) from e
                self.log.error(" %s", str(e))


# ----------------------------------------------------------------------------
# Codesigning and Packaging


class Codesigner:
    """Recursively codesign a macOS bundle with Developer ID support.

    This class handles the proper ordering of codesigning operations:
    1. Sign internal binaries (.so, .dylib) first
    2. Sign nested .app bundles
    3. Sign frameworks
    4. Sign the main bundle/runtime with entitlements

    Args:
        path: Path to the bundle to sign (.app, .bundle, .framework, .mxo)
        dev_id: Developer ID name (None or "-" for ad-hoc signing)
        entitlements: Path to entitlements.plist file
        dry_run: If True, only show what would be signed
        verify: If True, verify signatures after signing

    Environment Variables:
        DEV_ID: Developer ID (fallback if dev_id not provided)

    Example:
        signer = Codesigner("MyApp.app", dev_id="John Doe",
                            entitlements="entitlements.plist")
        signer.process()
    """

    FILE_EXTENSIONS: list[str] = SIGNABLE_FILE_EXTENSIONS
    FOLDER_EXTENSIONS: list[str] = SIGNABLE_FOLDER_EXTENSIONS

    def __init__(
        self,
        path: Pathlike,
        dev_id: str | None = None,
        entitlements: Pathlike | None = None,
        dry_run: bool = False,
        verify: bool = True,
    ) -> None:
        self.path = Path(path)
        self.dry_run = dry_run
        self.verify_after = verify
        self.log = logging.getLogger(self.__class__.__name__)

        # Resolve developer ID from parameter or environment
        if dev_id is None:
            dev_id = os.getenv(ENV_DEV_ID)
        self.authority: str | None
        if dev_id is not None and dev_id not in ("-", ""):
            # Validate Developer ID format
            validate_developer_id(dev_id)
            self.authority = f"Developer ID Application: {dev_id}"
        else:
            self.authority = None  # ad-hoc signing

        # Resolve entitlements path
        self.entitlements: Path | None
        if entitlements:
            self.entitlements = Path(entitlements)
            if not self.entitlements.exists():
                raise ConfigurationError(
                    f"Entitlements file not found: {self.entitlements}"
                )
        else:
            self.entitlements = None

        # Target collections
        self.targets_internals: set[Path] = set()
        self.targets_apps: set[Path] = set()
        self.targets_frameworks: set[Path] = set()
        self.targets_runtimes: set[Path] = set()

        # Build base codesign command parts
        self._cmd_codesign_base = [
            "codesign",
            "--sign",
            self.authority if self.authority else "-",
            "--timestamp",
            "--force",
        ]

    def run_command(self, command: list[str]) -> str:
        """Run a command and return its output.

        Args:
            command: The command as a list of arguments

        Returns:
            The command output

        Raises:
            CommandError: If the command fails
        """
        return run_command(command, dry_run=self.dry_run, log=self.log)

    def collect(self) -> None:
        """Walk the bundle and categorize all signable targets."""
        for root, folders, files in os.walk(self.path):
            root_path = Path(root)

            # Collect files
            for fname in files:
                fpath = root_path / fname
                if fpath.is_symlink():
                    continue
                if fpath.suffix in self.FILE_EXTENSIONS:
                    self.log.debug("added binary: %s", fpath)
                    self.targets_internals.add(fpath)

            # Collect folders/bundles
            for folder in folders:
                fpath = root_path / folder
                if fpath.is_symlink():
                    continue
                if fpath.suffix in self.FOLDER_EXTENSIONS:
                    self.log.debug("added bundle: %s", fpath)
                    if fpath.suffix == ".framework":
                        self.targets_frameworks.add(fpath)
                    elif fpath.suffix == ".app":
                        self.targets_apps.add(fpath)
                    else:
                        self.targets_internals.add(fpath)

    def sign_internal_binary(self, path: Path) -> None:
        """Sign an internal binary without runtime hardening.

        Args:
            path: Path to the binary to sign
        """
        codesign_cmd = self._cmd_codesign_base + [str(path)]
        self.log.info("signing internal: %s", path)
        self.run_command(codesign_cmd)

    def sign_runtime(self, path: Path | None = None) -> None:
        """Sign with runtime hardening and optional entitlements.

        Args:
            path: Path to sign (defaults to main bundle path)
        """
        if path is None:
            path = self.path

        cmd_parts = self._cmd_codesign_base + ["--options", "runtime"]
        if self.entitlements:
            cmd_parts.extend(["--entitlements", str(self.entitlements)])
        cmd_parts.append(str(path))

        self.log.info("signing runtime: %s", path)
        self.run_command(cmd_parts)

    def verify_signature(self, path: Path) -> bool:
        """Verify codesigning of a path.

        Args:
            path: Path to verify

        Returns:
            True if verification succeeds
        """
        try:
            self.run_command(["codesign", "--verify", "--verbose", str(path)])
            self.log.info("verified: %s", path)
            return True
        except CommandError as e:
            self.log.error("verification failed for %s: %s", path, e)
            return False

    def _section(self, *args: str) -> None:
        """Display a section header."""
        print()
        print("-" * 79)
        print(*args)

    def process(self) -> None:
        """Execute the full signing workflow."""
        self._section("PROCESSING:", str(self.path))

        self._section("COLLECTING...")
        if not self.targets_internals:
            self.collect()

        self._section("SIGNING INTERNAL TARGETS")
        for path in self.targets_internals:
            self.sign_internal_binary(path)

        self._section("SIGNING APPS")
        for path in self.targets_apps:
            # Sign executables inside .app first
            macos_path = path / "Contents" / "MacOS"
            if macos_path.exists():
                for exe in macos_path.iterdir():
                    if exe.is_file() and not exe.is_symlink():
                        self.sign_internal_binary(exe)
            self.sign_runtime(path)

        self._section("SIGNING FRAMEWORKS")
        for path in self.targets_frameworks:
            self.sign_internal_binary(path)

        self._section("SIGNING MAIN RUNTIME")
        self.sign_runtime()

        if self.verify_after and not self.dry_run:
            self._section("VERIFYING SIGNATURE")
            if not self.verify_signature(self.path):
                raise CodesignError(
                    f"Signature verification failed: {self.path}"
                )

        self.log.info("DONE!")

    def process_dry_run(self) -> None:
        """Show what would be signed without making changes."""

        def relative(p: Path) -> str:
            return str(p).replace(str(self.path), "")

        self._section("PROCESSING:", str(self.path))

        self._section("COLLECTING...")
        if not self.targets_internals:
            self.collect()

        self._section("SIGNING INTERNAL TARGETS")
        for path in self.targets_internals:
            print("  internal:", relative(path))

        self._section("SIGNING APPS")
        for path in self.targets_apps:
            print("  app:", relative(path))
            macos_path = path / "Contents" / "MacOS"
            if macos_path.exists():
                for exe in macos_path.iterdir():
                    if exe.is_file() and not exe.is_symlink():
                        print("    app.exe:", relative(exe))
            print("    app.runtime:", relative(path))

        self._section("SIGNING FRAMEWORKS")
        for path in self.targets_frameworks:
            print("  framework:", relative(path))

        self._section("SIGNING MAIN RUNTIME")
        print("  main.runtime:", str(self.path))

        self.log.info("DONE (dry run)!")


class Packager:
    """Creates, signs, notarizes, and staples a DMG for distribution.

    This class orchestrates the full release workflow:
    1. Sign contents with Developer ID
    2. Create DMG from source folder/bundle
    3. Sign the DMG with Developer ID
    4. Submit to Apple for notarization
    5. Staple the notarization ticket

    Args:
        source: Path to the bundle or folder to package
        output: Path for the output DMG file (default: {source.stem}.dmg)
        volume_name: Name for the mounted volume (default: source name)
        dev_id: Developer ID name
        keychain_profile: Keychain profile for notarytool
        entitlements: Path to entitlements.plist file
        dry_run: If True, show commands without executing
        sign_contents: If True, sign bundle contents before packaging

    Environment Variables:
        DEV_ID: Developer ID (fallback if dev_id not provided)
        KEYCHAIN_PROFILE: Keychain profile name (fallback)

    Example:
        packager = Packager("MyApp.app", output="MyApp-1.0.dmg")
        packager.process()
    """

    def __init__(
        self,
        source: Pathlike,
        output: Pathlike | None = None,
        volume_name: str | None = None,
        dev_id: str | None = None,
        keychain_profile: str | None = None,
        entitlements: Pathlike | None = None,
        dry_run: bool = False,
        sign_contents: bool = True,
    ) -> None:
        self.source = Path(source)
        if not self.source.exists():
            raise ConfigurationError(f"Source does not exist: {self.source}")

        # Output path defaults to source.dmg in same directory
        if output:
            self.output = Path(output)
        else:
            self.output = self.source.parent / f"{self.source.stem}.dmg"

        # Volume name defaults to source name
        self.volume_name = volume_name or self.source.stem

        # Resolve developer ID from parameter or environment
        self.dev_id = dev_id or os.getenv(ENV_DEV_ID)
        if not self.dev_id or self.dev_id == "-":
            self.dev_id = None
        elif self.dev_id:
            # Validate Developer ID format
            validate_developer_id(self.dev_id)

        # Resolve keychain profile from parameter or environment
        self.keychain_profile = keychain_profile or os.getenv(
            ENV_KEYCHAIN_PROFILE
        )

        # Entitlements path
        self.entitlements = Path(entitlements) if entitlements else None

        self.dry_run = dry_run
        self.should_sign_contents = sign_contents
        self.log = logging.getLogger(self.__class__.__name__)

    def run_command(self, command: list[str]) -> str:
        """Run a command and return its output."""
        return run_command(command, dry_run=self.dry_run, log=self.log)

    def sign_bundle_contents(self) -> None:
        """Recursively sign all bundles in source using Codesigner."""
        if not self.dev_id:
            self.log.warning(
                "No Developer ID provided, skipping content signing"
            )
            return

        self.log.info("Signing contents of %s", self.source)

        # If source is a bundle, sign it directly
        if self.source.suffix in Codesigner.FOLDER_EXTENSIONS:
            signer = Codesigner(
                path=self.source,
                dev_id=self.dev_id,
                entitlements=self.entitlements,
                dry_run=self.dry_run,
            )
            if self.dry_run:
                signer.process_dry_run()
            else:
                signer.process()
        else:
            # Source is a folder - sign each bundle inside
            for item in self.source.iterdir():
                if item.suffix in Codesigner.FOLDER_EXTENSIONS:
                    signer = Codesigner(
                        path=item,
                        dev_id=self.dev_id,
                        entitlements=self.entitlements,
                        dry_run=self.dry_run,
                    )
                    if self.dry_run:
                        signer.process_dry_run()
                    else:
                        signer.process()

    def create_dmg(self) -> Path:
        """Create DMG from source using hdiutil.

        Returns:
            Path to the created DMG file
        """
        self.log.info("Creating DMG: %s", self.output)

        # Remove existing DMG if present
        if self.output.exists() and not self.dry_run:
            self.output.unlink()

        command = [
            "hdiutil",
            "create",
            "-volname",
            self.volume_name,
            "-srcfolder",
            str(self.source),
            "-ov",
            "-format",
            "UDZO",
            str(self.output),
        ]
        self.run_command(command)

        if not self.dry_run and not self.output.exists():
            raise PackagingError(f"Failed to create DMG: {self.output}")

        return self.output

    def sign_dmg(self) -> None:
        """Sign the DMG with Developer ID."""
        if not self.dev_id:
            raise ConfigurationError(
                "Developer ID required for DMG signing. "
                "Set DEV_ID environment variable or pass dev_id parameter."
            )

        self.log.info("Signing DMG: %s", self.output)
        command = [
            "codesign",
            "--sign",
            f"Developer ID Application: {self.dev_id}",
            "--force",
            "--verbose",
            "--options",
            "runtime",
            str(self.output),
        ]
        self.run_command(command)

    def notarize_dmg(self) -> None:
        """Submit DMG to Apple for notarization and wait.

        Raises:
            NotarizationError: If notarization fails
            ConfigurationError: If keychain profile not configured
        """
        if not self.keychain_profile:
            raise ConfigurationError(
                "Keychain profile required for notarization. "
                "Set KEYCHAIN_PROFILE environment variable or pass "
                "keychain_profile parameter."
            )

        self.log.info("Notarizing DMG: %s", self.output)
        command = [
            "xcrun",
            "notarytool",
            "submit",
            str(self.output),
            "--keychain-profile",
            self.keychain_profile,
            "--wait",
        ]
        try:
            if self.dry_run:
                self.run_command(command)
            else:
                # Show progress spinner during notarization (can take minutes)
                with ProgressSpinner("Waiting for notarization"):
                    self.run_command(command)
        except CommandError as e:
            raise NotarizationError(
                f"Notarization failed for {self.output}: {e}"
            ) from e

    def staple_dmg(self) -> None:
        """Staple the notarization ticket to the DMG."""
        self.log.info("Stapling DMG: %s", self.output)
        command = ["xcrun", "stapler", "staple", str(self.output)]
        try:
            self.run_command(command)
        except CommandError as e:
            raise NotarizationError(
                f"Stapling failed for {self.output}: {e}"
            ) from e

    def process(
        self,
        notarize: bool = True,
        staple: bool = True,
    ) -> Path:
        """Execute the full packaging workflow.

        Args:
            notarize: Whether to notarize the DMG (requires keychain_profile)
            staple: Whether to staple the notarization ticket

        Returns:
            Path to the created DMG file
        """
        self.log.info("Starting packaging workflow for %s", self.source)

        # Step 1: Sign contents if requested
        if self.should_sign_contents:
            self.sign_bundle_contents()

        # Step 2: Create DMG
        self.create_dmg()

        # Step 3: Sign DMG (requires dev_id)
        if self.dev_id:
            self.sign_dmg()
        else:
            self.log.warning("Skipping DMG signing (no Developer ID)")

        # Step 4: Notarize (requires keychain_profile)
        if notarize and self.keychain_profile:
            self.notarize_dmg()
        elif notarize:
            self.log.warning("Skipping notarization (no keychain profile)")

        # Step 5: Staple (only if notarized)
        if staple and notarize and self.keychain_profile:
            self.staple_dmg()
        elif staple and notarize:
            self.log.warning("Skipping stapling (not notarized)")

        self.log.info("Packaging complete: %s", self.output)
        return self.output


# ----------------------------------------------------------------------------
# Functional API


def make_bundle(
    target: Pathlike,
    version: str = "1.0",
    add_to_resources: list[str] | None = None,
    base_id: str = "org.me",
    extension: str = ".app",
    codesign: bool = True,
    icon: Pathlike | None = None,
    min_system_version: str = DEFAULT_MIN_SYSTEM_VERSION,
    dry_run: bool = False,
) -> Path:
    """Create a macOS application bundle from an executable.

    This is a convenience function that creates a Bundle instance
    and calls create() on it.

    Args:
        target: Path to the target executable
        version: Bundle version string (default: "1.0")
        add_to_resources: List of paths to add to Resources folder
        base_id: Bundle identifier prefix (default: DEFAULT_BUNDLE_ID)
        extension: Bundle extension (default: DEFAULT_BUNDLE_EXT)
        codesign: Whether to apply ad-hoc code signing (default: True)
        icon: Path to icon file (.icns) to include in bundle
        min_system_version: Minimum macOS version (default: "10.13")
        dry_run: If True, only show what would be done

    Returns:
        Path to the created bundle

    Example:
        bundle_path = make_bundle("/path/to/myapp", version="2.0")
    """
    bundle = Bundle(
        target=target,
        version=version,
        add_to_resources=add_to_resources,
        base_id=base_id,
        extension=extension,
        codesign=codesign,
        icon=icon,
        min_system_version=min_system_version,
        dry_run=dry_run,
    )
    return bundle.create()


# ----------------------------------------------------------------------------
# Command-line interface


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    """Add common options to a parser."""
    parser.add_argument(
        "--no-sign",
        action="store_true",
        help="disable ad-hoc codesigning",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="enable verbose/debug logging",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable colored output",
    )


def _cmd_create(args: argparse.Namespace) -> None:
    """Handle 'create' subcommand."""
    setup_logging(args.verbose, not args.no_color)
    log = logging.getLogger("macbundler")

    # Load config and apply defaults
    config = get_config()
    version = args.version
    if version == "1.0":  # Check if using default
        version = (
            get_config_value(config, "create", "version", version) or version
        )
    base_id = args.id
    if base_id == DEFAULT_BUNDLE_ID:  # Check if using default
        base_id = get_config_value(config, "create", "id", base_id) or base_id
    extension = args.extension
    if extension == DEFAULT_BUNDLE_EXT:  # Check if using default
        extension = (
            get_config_value(config, "create", "extension", extension)
            or extension
        )
    icon = args.icon
    if icon is None:
        icon = get_config_value(config, "create", "icon")
    min_system_version = args.min_system_version
    if (
        min_system_version == DEFAULT_MIN_SYSTEM_VERSION
    ):  # Check if using default
        min_system_version = (
            get_config_value(
                config, "create", "min_system_version", min_system_version
            )
            or min_system_version
        )

    target = Path(args.executable)
    if not target.exists():
        log.error("Target executable does not exist: %s", target)
        sys.exit(1)

    bundle = Bundle(
        target=target,
        version=version,
        add_to_resources=args.resource,
        base_id=base_id,
        extension=extension,
        codesign=not args.no_sign,
        icon=icon,
        min_system_version=min_system_version,
        dry_run=args.dry_run,
    )
    bundle_path = bundle.create()
    log.info("Created: %s", bundle_path)


def _cmd_fix(args: argparse.Namespace) -> None:
    """Handle 'fix' subcommand."""
    setup_logging(args.verbose, not args.no_color)
    log = logging.getLogger("macbundler")

    bundler = DylibBundler(
        dest_dir=Path(args.dest),
        overwrite_dir=args.force,
        create_dir=True,
        codesign=not args.no_sign,
        inside_lib_path=args.prefix,
        files_to_fix=[Path(f) for f in args.files],
        prefixes_to_ignore=[Path(p) for p in (args.exclude or [])],
        search_paths=[Path(p) for p in (args.search or [])],
        dry_run=args.dry_run,
    )

    log.info("Collecting dependencies")
    for file in bundler.files_to_fix:
        bundler.collect_dependencies(file)

    bundler.collect_sub_dependencies()
    bundler.process_collected_deps()


def _cmd_sign(args: argparse.Namespace) -> None:
    """Handle 'sign' subcommand."""
    setup_logging(args.verbose, not args.no_color)
    log = logging.getLogger("macbundler")

    # Load config and apply defaults
    config = get_config()
    dev_id = args.dev_id
    if dev_id is None:
        dev_id = get_config_value(config, "sign", "dev_id")
    entitlements = args.entitlements
    if entitlements is None:
        entitlements = get_config_value(config, "sign", "entitlements")

    bundle = Path(args.bundle)
    if not bundle.exists():
        log.error("Bundle does not exist: %s", bundle)
        sys.exit(1)

    signer = Codesigner(
        path=bundle,
        dev_id=dev_id,
        entitlements=entitlements,
        dry_run=args.dry_run,
        verify=not args.no_verify,
    )

    if args.dry_run:
        signer.process_dry_run()
    else:
        signer.process()

    log.info("Signed: %s", bundle)


def _cmd_package(args: argparse.Namespace) -> None:
    """Handle 'package' subcommand."""
    setup_logging(args.verbose, not args.no_color)
    log = logging.getLogger("macbundler")

    # Load config and apply defaults
    config = get_config()
    dev_id = args.dev_id
    if dev_id is None:
        dev_id = get_config_value(config, "package", "dev_id")
    keychain_profile = args.keychain_profile
    if keychain_profile is None:
        keychain_profile = get_config_value(
            config, "package", "keychain_profile"
        )
    entitlements = args.entitlements
    if entitlements is None:
        entitlements = get_config_value(config, "package", "entitlements")

    source = Path(args.source)
    if not source.exists():
        log.error("Source does not exist: %s", source)
        sys.exit(1)

    packager = Packager(
        source=source,
        output=args.output,
        volume_name=args.name,
        dev_id=dev_id,
        keychain_profile=keychain_profile,
        entitlements=entitlements,
        dry_run=args.dry_run,
        sign_contents=not args.no_sign,
    )

    dmg_path = packager.process(
        notarize=not args.no_notarize,
        staple=not args.no_staple,
    )
    log.info("Created: %s", dmg_path)


def main() -> None:
    """Command line interface for macbundler."""
    try:
        parser = argparse.ArgumentParser(
            prog="macbundler",
            description="Create macOS app bundles and bundle dynamic libraries.",
            epilog=(
                "Examples:\n"
                "  macbundler create myapp\n"
                "  macbundler create myapp -v 2.0 -i com.example.myapp\n"
                "  macbundler fix App.app/Contents/MacOS/main -d App.app/Contents/libs/\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

        subparsers = parser.add_subparsers(
            title="commands",
            dest="command",
            required=True,
        )

        # --- create subcommand ---
        create_parser = subparsers.add_parser(
            "create",
            help="create a new .app bundle from an executable",
            description="Create a new macOS .app bundle from an executable.",
            epilog=(
                "Examples:\n"
                "  macbundler create myapp\n"
                "  macbundler create myapp --version 2.0 --id com.example.myapp\n"
                "  macbundler create myapp -e .plugin\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        create_parser.add_argument(
            "executable",
            help="path to the executable to bundle",
        )
        create_parser.add_argument(
            "-o",
            "--output",
            help="output directory (default: same as executable)",
        )
        create_parser.add_argument(
            "-v",
            "--version",
            default="1.0",
            help="bundle version (default: 1.0)",
        )
        create_parser.add_argument(
            "-i",
            "--id",
            default=DEFAULT_BUNDLE_ID,
            help=f"bundle identifier prefix (default: {DEFAULT_BUNDLE_ID})",
        )
        create_parser.add_argument(
            "-e",
            "--extension",
            default=DEFAULT_BUNDLE_EXT,
            help=f"bundle extension (default: {DEFAULT_BUNDLE_EXT})",
        )
        create_parser.add_argument(
            "-r",
            "--resource",
            action="append",
            metavar="PATH",
            help="add resource to bundle (repeatable)",
        )
        create_parser.add_argument(
            "--icon",
            metavar="FILE",
            help="path to icon file (.icns)",
        )
        create_parser.add_argument(
            "--min-system-version",
            default=DEFAULT_MIN_SYSTEM_VERSION,
            metavar="VERSION",
            help=f"minimum macOS version (default: {DEFAULT_MIN_SYSTEM_VERSION})",
        )
        create_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="show what would be done without doing it",
        )
        _add_common_options(create_parser)
        create_parser.set_defaults(func=_cmd_create)

        # --- fix subcommand ---
        fix_parser = subparsers.add_parser(
            "fix",
            help="fix dylib paths in existing files",
            description="Bundle dynamic libraries and fix paths in existing files.",
            epilog=(
                "Examples:\n"
                "  macbundler fix App.app/Contents/MacOS/main -d App.app/Contents/libs/\n"
                "  macbundler fix main -d ./libs/ -s /opt/local/lib\n"
                "  macbundler fix main plugin.so -d ./libs/ --force\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        fix_parser.add_argument(
            "files",
            nargs="+",
            help="files to fix (executables or plugins)",
        )
        fix_parser.add_argument(
            "-d",
            "--dest",
            required=True,
            metavar="DIR",
            help="destination directory for bundled libraries",
        )
        fix_parser.add_argument(
            "-p",
            "--prefix",
            default=DEFAULT_LIB_PATH,
            metavar="PATH",
            help=f"library install path prefix (default: {DEFAULT_LIB_PATH})",
        )
        fix_parser.add_argument(
            "-s",
            "--search",
            action="append",
            metavar="DIR",
            help="additional search path (repeatable)",
        )
        fix_parser.add_argument(
            "-x",
            "--exclude",
            action="append",
            metavar="DIR",
            help="exclude libraries from directory (repeatable)",
        )
        fix_parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="overwrite destination directory if it exists",
        )
        fix_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="show what would be done without doing it",
        )
        _add_common_options(fix_parser)
        fix_parser.set_defaults(func=_cmd_fix)

        # --- sign subcommand ---
        sign_parser = subparsers.add_parser(
            "sign",
            help="codesign a bundle with Developer ID",
            description="Recursively codesign a macOS bundle with Developer ID.",
            epilog=(
                "Examples:\n"
                "  macbundler sign MyApp.app\n"
                "  macbundler sign MyApp.app -i 'John Doe' -e entitlements.plist\n"
                "  macbundler sign MyApp.app --dry-run\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sign_parser.add_argument(
            "bundle",
            help="path to the bundle to sign (.app, .bundle, .framework, .mxo)",
        )
        sign_parser.add_argument(
            "-i",
            "--dev-id",
            metavar="ID",
            help="Developer ID name (or set DEV_ID env var)",
        )
        sign_parser.add_argument(
            "-e",
            "--entitlements",
            metavar="FILE",
            help="path to entitlements.plist",
        )
        sign_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="show what would be signed without signing",
        )
        sign_parser.add_argument(
            "--no-verify",
            action="store_true",
            help="skip signature verification",
        )
        sign_parser.add_argument(
            "--verbose",
            action="store_true",
            help="enable verbose/debug logging",
        )
        sign_parser.add_argument(
            "--no-color",
            action="store_true",
            help="disable colored output",
        )
        sign_parser.set_defaults(func=_cmd_sign)

        # --- package subcommand ---
        package_parser = subparsers.add_parser(
            "package",
            help="create, sign, notarize, and staple a DMG",
            description="Create a DMG, sign it, notarize with Apple, and staple.",
            epilog=(
                "Examples:\n"
                "  macbundler package MyApp.app\n"
                "  macbundler package MyApp.app -o releases/MyApp-1.0.dmg\n"
                "  macbundler package MyApp.app -i 'John Doe' -k AC_PROFILE\n"
                "  macbundler package dist/ --no-notarize\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        package_parser.add_argument(
            "source",
            help="path to bundle or folder to package",
        )
        package_parser.add_argument(
            "-o",
            "--output",
            metavar="FILE",
            help="output DMG path (default: <source>.dmg)",
        )
        package_parser.add_argument(
            "-n",
            "--name",
            metavar="NAME",
            help="volume name (default: source name)",
        )
        package_parser.add_argument(
            "-i",
            "--dev-id",
            metavar="ID",
            help="Developer ID name (or set DEV_ID env var)",
        )
        package_parser.add_argument(
            "-k",
            "--keychain-profile",
            metavar="PROFILE",
            help="keychain profile for notarytool (or set KEYCHAIN_PROFILE env var)",
        )
        package_parser.add_argument(
            "-e",
            "--entitlements",
            metavar="FILE",
            help="path to entitlements.plist",
        )
        package_parser.add_argument(
            "--no-sign",
            action="store_true",
            help="skip signing bundle contents",
        )
        package_parser.add_argument(
            "--no-notarize",
            action="store_true",
            help="skip notarization",
        )
        package_parser.add_argument(
            "--no-staple",
            action="store_true",
            help="skip stapling",
        )
        package_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="show commands without executing",
        )
        package_parser.add_argument(
            "--verbose",
            action="store_true",
            help="enable verbose/debug logging",
        )
        package_parser.add_argument(
            "--no-color",
            action="store_true",
            help="disable colored output",
        )
        package_parser.set_defaults(func=_cmd_package)

        args = parser.parse_args()
        args.func(args)

    except BundlerError as e:
        logging.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logging.error("Unexpected error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
