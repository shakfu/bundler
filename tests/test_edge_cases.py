"""Tests for edge cases and error handling paths."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from macbundler import (
    CommandError,
    ConfigurationError,
    Dependency,
    DylibBundler,
    NotarizationError,
    Packager,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


@pytest.fixture
def sample_executable(temp_dir):
    """Create a sample executable file."""
    exe_path = temp_dir / "test_executable"
    exe_path.touch()
    exe_path.chmod(0o755)
    return exe_path


@pytest.fixture
def bundler_instance(temp_dir, sample_executable):
    """Create a DylibBundler instance with test configuration."""
    lib_path = temp_dir / "libs"
    lib_path.mkdir()
    return DylibBundler(
        dest_dir=lib_path,
        overwrite_dir=True,
        create_dir=True,
        codesign=False,
        inside_lib_path="@executable_path/../libs/",
        files_to_fix=[sample_executable],
        prefixes_to_ignore=[],
        search_paths=[],
    )


class TestDependencyUserInput:
    """Tests for Dependency._get_user_input_dir_for_file() interactive prompt."""

    def test_user_input_found_in_search_path(self, bundler_instance, temp_dir):
        """Test that file is found in search path without prompting."""
        # Create a library in a search path
        search_path = temp_dir / "search"
        search_path.mkdir()
        lib_file = search_path / "libtest.dylib"
        lib_file.touch()

        bundler_instance.add_search_path(search_path)

        # Create a dependency that needs to find libtest.dylib
        dep = Dependency.__new__(Dependency)
        dep.parent = bundler_instance
        dep.log = bundler_instance.log
        dep.filename = "libtest.dylib"

        # Should find without prompting
        result = dep._get_user_input_dir_for_file("libtest.dylib")
        assert result == search_path

    @patch("builtins.input")
    def test_user_input_valid_path(
        self, mock_input, bundler_instance, temp_dir
    ):
        """Test user provides valid directory path."""
        # Create a library
        lib_dir = temp_dir / "custom_libs"
        lib_dir.mkdir()
        lib_file = lib_dir / "libcustom.dylib"
        lib_file.touch()

        mock_input.return_value = str(lib_dir)

        dep = Dependency.__new__(Dependency)
        dep.parent = bundler_instance
        dep.log = bundler_instance.log
        dep.filename = "libcustom.dylib"

        result = dep._get_user_input_dir_for_file("libcustom.dylib")
        assert result == lib_dir

    @patch("builtins.input")
    def test_user_input_quit(self, mock_input, bundler_instance):
        """Test user quits dependency resolution."""
        mock_input.return_value = "quit"

        dep = Dependency.__new__(Dependency)
        dep.parent = bundler_instance
        dep.log = bundler_instance.log
        dep.filename = "libmissing.dylib"

        with pytest.raises(ConfigurationError, match="User aborted"):
            dep._get_user_input_dir_for_file("libmissing.dylib")

    @patch("builtins.input")
    def test_user_input_invalid_then_valid(
        self, mock_input, bundler_instance, temp_dir
    ):
        """Test user provides invalid path first, then valid path."""
        # Create a library
        lib_dir = temp_dir / "libs2"
        lib_dir.mkdir()
        lib_file = lib_dir / "libfound.dylib"
        lib_file.touch()

        # First call returns invalid path, second returns valid
        mock_input.side_effect = ["/nonexistent/path", str(lib_dir)]

        dep = Dependency.__new__(Dependency)
        dep.parent = bundler_instance
        dep.log = bundler_instance.log
        dep.filename = "libfound.dylib"

        result = dep._get_user_input_dir_for_file("libfound.dylib")
        assert result == lib_dir
        assert mock_input.call_count == 2

    @patch("builtins.input")
    def test_user_input_multiple_invalid_then_quit(
        self, mock_input, bundler_instance
    ):
        """Test user provides multiple invalid paths then quits."""
        mock_input.side_effect = ["/invalid1", "/invalid2", "quit"]

        dep = Dependency.__new__(Dependency)
        dep.parent = bundler_instance
        dep.log = bundler_instance.log
        dep.filename = "libnotfound.dylib"

        with pytest.raises(ConfigurationError, match="User aborted"):
            dep._get_user_input_dir_for_file("libnotfound.dylib")
        assert mock_input.call_count == 3


class TestARMSigningWorkaround:
    """Tests for ARM Mac signing workaround path in adhoc_codesign."""

    @patch("subprocess.run")
    def test_adhoc_codesign_success(self, mock_run, bundler_instance, temp_dir):
        """Test successful ad-hoc codesigning."""
        bundler_instance.can_codesign = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        test_file = temp_dir / "test.dylib"
        test_file.touch()

        bundler_instance.adhoc_codesign(test_file)
        mock_run.assert_called_once()

    @patch("subprocess.run")
    @patch("shutil.copy2")
    @patch("shutil.move")
    @patch("shutil.rmtree")
    def test_adhoc_codesign_workaround_non_arm(
        self,
        mock_rmtree,
        mock_move,
        mock_copy,
        mock_run,
        bundler_instance,
        temp_dir,
    ):
        """Test workaround path on non-ARM (failure logs error but doesn't raise)."""
        bundler_instance.can_codesign = True

        # First codesign fails, machine returns non-arm, second codesign fails
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "codesign"),  # Initial sign fails
            MagicMock(returncode=0, stdout="x86_64", stderr=""),  # machine
            subprocess.CalledProcessError(1, "codesign"),  # Retry fails
        ]

        test_file = temp_dir / "test.dylib"
        test_file.touch()

        # Should not raise on non-ARM, just log error
        bundler_instance.adhoc_codesign(test_file)

    @patch("subprocess.run")
    @patch("shutil.copy2")
    @patch("shutil.move")
    @patch("shutil.rmtree")
    def test_adhoc_codesign_workaround_arm_raises(
        self,
        mock_rmtree,
        mock_move,
        mock_copy,
        mock_run,
        bundler_instance,
        temp_dir,
    ):
        """Test workaround path on ARM raises CommandError on failure."""
        bundler_instance.can_codesign = True

        # First codesign fails, machine returns arm, second codesign fails
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "codesign"),  # Initial sign fails
            MagicMock(returncode=0, stdout="arm64", stderr=""),  # machine
            subprocess.CalledProcessError(1, "codesign"),  # Retry fails
        ]

        test_file = temp_dir / "test.dylib"
        test_file.touch()

        with pytest.raises(CommandError, match="ARM"):
            bundler_instance.adhoc_codesign(test_file)

    @patch("subprocess.run")
    @patch("shutil.copy2")
    @patch("shutil.move")
    @patch("shutil.rmtree")
    def test_adhoc_codesign_workaround_success_after_copy(
        self,
        mock_rmtree,
        mock_move,
        mock_copy,
        mock_run,
        bundler_instance,
        temp_dir,
    ):
        """Test workaround succeeds after copy/move cycle."""
        bundler_instance.can_codesign = True

        # First codesign fails, machine command, second codesign succeeds
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "codesign"),  # Initial sign fails
            MagicMock(returncode=0, stdout="arm64", stderr=""),  # machine
            MagicMock(returncode=0, stdout="", stderr=""),  # Retry succeeds
        ]

        test_file = temp_dir / "test.dylib"
        test_file.touch()

        # Should succeed without raising
        bundler_instance.adhoc_codesign(test_file)
        mock_copy.assert_called_once()
        mock_move.assert_called_once()
        mock_rmtree.assert_called_once()

    @patch("subprocess.run")
    def test_adhoc_codesign_machine_command_fails(
        self, mock_run, bundler_instance, temp_dir
    ):
        """Test when machine command fails, is_arm defaults to False."""
        bundler_instance.can_codesign = True

        # First codesign fails, machine fails, retry codesign fails
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "codesign"),
            subprocess.CalledProcessError(1, "machine"),  # machine fails
            subprocess.CalledProcessError(1, "codesign"),
        ]

        test_file = temp_dir / "test.dylib"
        test_file.touch()

        # Should not raise (is_arm defaults to False)
        bundler_instance.adhoc_codesign(test_file)

    def test_adhoc_codesign_disabled(self, bundler_instance, temp_dir):
        """Test that adhoc_codesign does nothing when disabled."""
        bundler_instance.can_codesign = False

        test_file = temp_dir / "test.dylib"
        test_file.touch()

        with patch("subprocess.run") as mock_run:
            bundler_instance.adhoc_codesign(test_file)
            mock_run.assert_not_called()


class TestNotarizationFailureHandling:
    """Tests for notarization failure handling."""

    @pytest.fixture
    def sample_bundle(self, temp_dir):
        """Create a sample bundle for packaging tests."""
        bundle = temp_dir / "Test.app"
        contents = bundle / "Contents"
        macos = contents / "MacOS"
        macos.mkdir(parents=True)
        (macos / "Test").touch()
        return bundle

    @patch("subprocess.run")
    def test_notarize_dmg_failure(self, mock_run, sample_bundle):
        """Test NotarizationError is raised when notarytool fails."""
        packager = Packager(
            sample_bundle,
            dev_id="Test",
            keychain_profile="TestProfile",
            sign_contents=False,
        )
        packager.output.write_bytes(b"fake dmg")

        mock_run.side_effect = subprocess.CalledProcessError(
            1, "xcrun notarytool", stderr="Invalid credentials"
        )

        with pytest.raises(NotarizationError, match="Notarization failed"):
            packager.notarize_dmg()

    @patch("subprocess.run")
    def test_staple_dmg_failure(self, mock_run, sample_bundle):
        """Test NotarizationError is raised when stapling fails."""
        packager = Packager(sample_bundle, sign_contents=False)
        packager.output.write_bytes(b"fake dmg")

        mock_run.side_effect = subprocess.CalledProcessError(
            1, "xcrun stapler", stderr="No ticket found"
        )

        with pytest.raises(NotarizationError, match="Stapling failed"):
            packager.staple_dmg()

    @patch("subprocess.run")
    def test_notarize_requires_keychain_profile(self, mock_run, sample_bundle):
        """Test ConfigurationError when keychain_profile is missing."""
        packager = Packager(sample_bundle, dev_id="Test", sign_contents=False)
        packager.output.write_bytes(b"fake dmg")

        with pytest.raises(
            ConfigurationError, match="Keychain profile required"
        ):
            packager.notarize_dmg()

    @patch("subprocess.run")
    def test_process_skips_notarize_without_profile(
        self, mock_run, sample_bundle
    ):
        """Test process() skips notarization when no keychain_profile."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        packager = Packager(sample_bundle, dev_id="Test", sign_contents=False)

        # Side effect to create DMG
        def create_dmg(*args, **kwargs):
            packager.output.write_bytes(b"fake dmg")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = create_dmg

        # Should not raise, just skip notarization
        packager.process(notarize=True, staple=False)


class TestEdgeCases:
    """Tests for edge cases like symlinks, unicode paths, special characters."""

    def test_unicode_paths(self, temp_dir, sample_executable):
        """Test handling of unicode characters in paths."""
        # Create directory with unicode name
        unicode_dir = temp_dir / "libs"
        unicode_dir.mkdir()

        bundler = DylibBundler(
            dest_dir=unicode_dir,
            overwrite_dir=True,
            create_dir=True,
            codesign=False,
            files_to_fix=[sample_executable],
        )

        assert bundler.dest_dir == unicode_dir

    def test_paths_with_spaces(self, temp_dir):
        """Test handling of paths with spaces."""
        spaced_dir = temp_dir / "path with spaces"
        spaced_dir.mkdir()

        exe_path = spaced_dir / "my executable"
        exe_path.touch()
        exe_path.chmod(0o755)

        libs_dir = spaced_dir / "my libs"
        libs_dir.mkdir()

        bundler = DylibBundler(
            dest_dir=libs_dir,
            overwrite_dir=True,
            create_dir=True,
            codesign=False,
            files_to_fix=[exe_path],
        )

        assert bundler.dest_dir == libs_dir
        assert exe_path in bundler.files_to_fix

    def test_symlink_to_directory(self, bundler_instance, temp_dir):
        """Test handling symlinks to directories in search paths."""
        # Create actual directory
        actual_dir = temp_dir / "actual_libs"
        actual_dir.mkdir()

        # Create library in actual directory
        lib_file = actual_dir / "libreal.dylib"
        lib_file.touch()

        # Create symlink to directory
        symlink_dir = temp_dir / "symlinked_libs"
        symlink_dir.symlink_to(actual_dir)

        # Add symlink directory as search path
        bundler_instance.add_search_path(symlink_dir)
        assert symlink_dir in bundler_instance.search_paths

    def test_symlink_to_file(self, bundler_instance, temp_dir):
        """Test handling symlinks to library files."""
        # Create actual library
        actual_lib = temp_dir / "libactual.dylib"
        actual_lib.touch()

        # Create symlink to library
        symlink_lib = temp_dir / "libsymlink.dylib"
        symlink_lib.symlink_to(actual_lib)

        # Dependency should follow symlink
        dep = Dependency(bundler_instance, symlink_lib, temp_dir / "exe")
        # The path should resolve to the actual file
        assert dep.get_original_path().resolve() == actual_lib.resolve()

    def test_broken_symlink(self, bundler_instance, temp_dir):
        """Test handling of broken symlinks."""
        # Create symlink to non-existent target
        broken_link = temp_dir / "broken.dylib"
        broken_link.symlink_to(temp_dir / "nonexistent.dylib")

        # Should handle gracefully (not crash)
        assert broken_link.is_symlink()
        assert not broken_link.exists()

    def test_circular_symlink_detection(self, temp_dir):
        """Test detection of circular symlinks in search paths."""
        # Create circular symlink structure
        dir_a = temp_dir / "dir_a"
        dir_a.mkdir()
        dir_b = temp_dir / "dir_b"
        dir_b.mkdir()

        # Create symlinks that point to each other
        link_in_a = dir_a / "to_b"
        link_in_a.symlink_to(dir_b)

        link_in_b = dir_b / "to_a"
        link_in_b.symlink_to(dir_a)

        # The structure exists
        assert link_in_a.is_symlink()
        assert link_in_b.is_symlink()

    def test_very_long_path(self, temp_dir, sample_executable):
        """Test handling of very long paths."""
        # Create nested directories with long names
        long_name = "a" * 50
        current = temp_dir
        for _ in range(5):
            current = current / long_name
        current.mkdir(parents=True)

        libs_dir = current / "libs"
        libs_dir.mkdir()

        bundler = DylibBundler(
            dest_dir=libs_dir,
            overwrite_dir=True,
            create_dir=True,
            codesign=False,
            files_to_fix=[sample_executable],
        )

        assert bundler.dest_dir == libs_dir

    def test_special_characters_in_path(self, temp_dir, sample_executable):
        """Test handling of special characters in paths."""
        special_dir = temp_dir / "libs-test_v1.0 (copy)"
        special_dir.mkdir()

        bundler = DylibBundler(
            dest_dir=special_dir,
            overwrite_dir=True,
            create_dir=True,
            codesign=False,
            files_to_fix=[sample_executable],
        )

        assert bundler.dest_dir == special_dir

    def test_dot_files_and_directories(self, bundler_instance, temp_dir):
        """Test handling of hidden files and directories."""
        # Create hidden directory
        hidden_dir = temp_dir / ".hidden_libs"
        hidden_dir.mkdir()

        # Create hidden library
        hidden_lib = hidden_dir / ".libhidden.dylib"
        hidden_lib.touch()

        # Add to search path
        bundler_instance.add_search_path(hidden_dir)
        assert hidden_dir in bundler_instance.search_paths

    def test_readonly_destination(self, temp_dir, sample_executable):
        """Test error handling when destination is read-only."""
        from macbundler import FileError

        readonly_dir = temp_dir / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)

        try:
            bundler = DylibBundler(
                dest_dir=readonly_dir / "libs",
                overwrite_dir=False,
                create_dir=True,
                codesign=False,
                files_to_fix=[sample_executable],
            )

            # Attempt to create should fail with FileError or PermissionError
            with pytest.raises((FileError, PermissionError)):
                bundler.create_dest_dir()
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)

    def test_dependency_with_version_suffix(self, bundler_instance, temp_dir):
        """Test dependencies with version numbers in filename."""
        lib_path = temp_dir / "libfoo.1.2.3.dylib"
        lib_path.touch()

        dep = Dependency(bundler_instance, lib_path, temp_dir / "exe")
        assert dep.filename == "libfoo.1.2.3.dylib"

    def test_dependency_symlink_chain(self, bundler_instance, temp_dir):
        """Test dependency with chain of symlinks."""
        # libfoo.dylib -> libfoo.1.dylib -> libfoo.1.0.dylib (actual)
        actual_lib = temp_dir / "libfoo.1.0.dylib"
        actual_lib.touch()

        link1 = temp_dir / "libfoo.1.dylib"
        link1.symlink_to(actual_lib)

        link2 = temp_dir / "libfoo.dylib"
        link2.symlink_to(link1)

        # Create dependency using the symlink
        dep = Dependency(bundler_instance, link2, temp_dir / "exe")
        # Should resolve through the chain
        assert dep.get_original_path().resolve() == actual_lib.resolve()


class TestCollectDependenciesEdgeCases:
    """Test edge cases in dependency collection."""

    @patch("subprocess.run")
    def test_otool_on_nonexistent_file(
        self, mock_run, bundler_instance, temp_dir
    ):
        """Test collect_dependencies on non-existent file."""
        from macbundler import FileError

        nonexistent = temp_dir / "nonexistent"

        with pytest.raises(FileError):
            bundler_instance._collect_dependency_lines(nonexistent)

    @patch("subprocess.run")
    def test_otool_failure(self, mock_run, bundler_instance, temp_dir):
        """Test handling when otool fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "otool")

        test_file = temp_dir / "test"
        test_file.touch()

        with pytest.raises(CommandError):
            bundler_instance._collect_dependency_lines(test_file)

    @patch("subprocess.run")
    def test_collect_rpaths_on_nonexistent_file(
        self, mock_run, bundler_instance, temp_dir
    ):
        """Test collect_rpaths gracefully handles non-existent file."""
        nonexistent = temp_dir / "nonexistent"

        # Should not raise, just log warning
        bundler_instance.collect_rpaths(nonexistent)
        mock_run.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
