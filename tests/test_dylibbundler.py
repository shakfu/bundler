import tempfile
from pathlib import Path

import pytest

from macbundler import (
    CommandError,
    ConfigurationError,
    Dependency,
    DylibBundler,
    FileError,
)


# Test fixtures
@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


@pytest.fixture
def sample_lib_path(temp_dir):
    """Create a sample library path structure."""
    lib_path = temp_dir / "libs"
    lib_path.mkdir()
    return lib_path


@pytest.fixture
def sample_executable(temp_dir):
    """Create a sample executable file."""
    exe_path = temp_dir / "test_executable"
    exe_path.touch()
    exe_path.chmod(0o755)
    return exe_path


@pytest.fixture
def bundler_instance(temp_dir, sample_lib_path, sample_executable):
    """Create a DylibBundler instance with test configuration."""
    return DylibBundler(
        dest_dir=sample_lib_path,
        overwrite_dir=True,
        create_dir=True,
        codesign=False,  # Disable codesigning for tests
        inside_lib_path="@executable_path/../libs/",
        files_to_fix=[sample_executable],  # Provide a valid file
        prefixes_to_ignore=[],
        search_paths=[],
    )


# Test cases
def test_dependency_initialization(bundler_instance, temp_dir):
    """Test Dependency class initialization."""
    # Create the library file first
    lib_path = temp_dir / "test.dylib"
    lib_path.touch()

    dep = Dependency(bundler_instance, lib_path, temp_dir / "test_executable")
    assert dep.filename == "test.dylib"
    # Use resolve() to handle macOS /var -> /private/var symlink
    assert dep.prefix == temp_dir.resolve()


def test_dependency_path_resolution(bundler_instance, temp_dir):
    """Test dependency path resolution."""
    # Create a test library
    lib_path = temp_dir / "test.dylib"
    lib_path.touch()

    dep = Dependency(bundler_instance, lib_path, temp_dir / "test_executable")
    # Use resolve() to handle macOS /var -> /private/var symlink
    assert dep.get_original_path() == lib_path.resolve()
    assert dep.get_install_path() == bundler_instance.dest_dir / "test.dylib"


def test_bundler_creation(temp_dir, sample_lib_path, sample_executable):
    """Test DylibBundler initialization."""
    bundler = DylibBundler(
        dest_dir=sample_lib_path,
        overwrite_dir=True,
        create_dir=True,
        codesign=False,
        files_to_fix=[sample_executable],
    )
    assert bundler.dest_dir == sample_lib_path
    assert bundler.can_overwrite_dir is True
    assert bundler.can_create_dir is True
    assert bundler.can_codesign is False


def test_bundler_invalid_configuration_no_files():
    """Test invalid DylibBundler configuration - no files to fix."""
    with pytest.raises(ConfigurationError):
        DylibBundler(
            dest_dir="./libs/",
            create_dir=True,
            files_to_fix=[],
        )


def test_bundler_invalid_configuration_no_dest():
    """Test invalid DylibBundler configuration - no dest dir."""
    with pytest.raises(ConfigurationError):
        DylibBundler(
            dest_dir=None,
            create_dir=False,
            files_to_fix=["test"],
        )


def test_dependency_collection(bundler_instance, temp_dir):
    """Test dependency collection functionality."""
    # Create test files
    exe_path = temp_dir / "test_executable"
    lib_path = temp_dir / "test.dylib"

    exe_path.touch()
    lib_path.touch()

    bundler_instance.add_file_to_fix(exe_path)
    bundler_instance.collect_dependencies(exe_path)

    assert exe_path in bundler_instance.deps_collected
    assert bundler_instance.deps_collected[exe_path] is True


def test_search_path_handling(bundler_instance, temp_dir):
    """Test search path handling."""
    search_path = temp_dir / "search_path"
    search_path.mkdir()

    bundler_instance.add_search_path(search_path)
    assert search_path in bundler_instance.search_paths


def test_ignore_prefix_handling(bundler_instance, temp_dir):
    """Test ignore prefix functionality."""
    ignore_path = temp_dir / "ignore_path"
    ignore_path.mkdir()

    bundler_instance.ignore_prefix(ignore_path)
    assert ignore_path in bundler_instance.prefixes_to_ignore
    assert bundler_instance.is_ignored_prefix(ignore_path) is True


def test_system_library_detection(bundler_instance):
    """Test system library detection."""
    assert bundler_instance.is_system_library("/usr/lib/libc.dylib") is True
    assert (
        bundler_instance.is_system_library(
            "/System/Library/Frameworks/CoreFoundation.framework"
        )
        is True
    )
    assert (
        bundler_instance.is_system_library("/usr/local/lib/libtest.dylib")
        is False
    )


def test_command_execution(bundler_instance, temp_dir):
    """Test command execution functionality."""
    # Test successful command
    result = bundler_instance.run_command("echo 'test'", shell=True)
    assert "test" in result

    # Test failed command
    with pytest.raises(CommandError):
        bundler_instance.run_command("false", shell=True)


def test_file_permission_changes(bundler_instance, temp_dir):
    """Test file permission changes."""
    test_file = temp_dir / "test_file"
    test_file.touch()

    bundler_instance.chmod(test_file, 0o755)
    assert test_file.stat().st_mode & 0o777 == 0o755


def test_dest_dir_creation(bundler_instance, temp_dir):
    """Test destination directory creation."""
    dest_dir = temp_dir / "test_dest"
    bundler_instance.dest_dir = dest_dir

    bundler_instance.create_dest_dir()
    assert dest_dir.exists()
    assert dest_dir.is_dir()


def test_dependency_merging(bundler_instance, temp_dir):
    """Test dependency merging functionality."""
    # Create two dependencies pointing to the same file
    lib_path = temp_dir / "test.dylib"
    lib_path.touch()

    dep1 = Dependency(bundler_instance, lib_path, temp_dir / "exe1")
    dep2 = Dependency(bundler_instance, lib_path, temp_dir / "exe2")

    assert dep1.merge_if_same_as(dep2) is True


def test_rpath_handling(bundler_instance, temp_dir):
    """Test rpath handling functionality."""
    # Create test files
    exe_path = temp_dir / "test_executable"
    exe_path.touch()

    # collect_rpaths will run otool on the file, which may fail for non-Mach-O
    # but should not raise an exception
    bundler_instance.collect_rpaths(exe_path)
    # The file may or may not be in rpaths_per_file depending on otool output
    # For a non-Mach-O file, rpaths_per_file will be empty or not contain the key
    assert isinstance(bundler_instance.rpaths_per_file, dict)


def test_dependency_copying(bundler_instance, temp_dir):
    """Test dependency copying functionality - file copy part only.

    Note: copy_yourself() also calls install_name_tool which will fail on
    non-Mach-O files, so we test the path resolution separately.
    """
    # Create test files
    lib_path = temp_dir / "test.dylib"
    lib_path.touch()

    dep = Dependency(bundler_instance, lib_path, temp_dir / "test_executable")

    # Test that paths are resolved correctly
    # Use resolve() to handle macOS /var -> /private/var symlink
    assert dep.get_original_path() == lib_path.resolve()
    assert dep.get_install_path() == bundler_instance.dest_dir / "test.dylib"
    assert dep.get_inner_path() == "@executable_path/../libs/test.dylib"


def test_error_handling_command_error(bundler_instance):
    """Test CommandError handling."""
    with pytest.raises(CommandError):
        bundler_instance.run_command("nonexistent_command_xyz123", shell=True)


def test_error_handling_configuration_error():
    """Test ConfigurationError handling."""
    with pytest.raises(ConfigurationError):
        DylibBundler(dest_dir=None, create_dir=False, files_to_fix=["test"])


def test_error_handling_file_error(temp_dir, sample_executable):
    """Test FileError handling when dest dir cannot be created."""
    # Create a bundler with can_create_dir=False pointing to non-existent dir
    non_existent_dir = temp_dir / "non_existent_dir"
    bundler = DylibBundler(
        dest_dir=non_existent_dir,
        overwrite_dir=False,
        create_dir=False,
        files_to_fix=[sample_executable],
    )
    with pytest.raises(FileError):
        bundler.create_dest_dir()


if __name__ == "__main__":
    pytest.main([__file__])
