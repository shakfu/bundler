"""Tests for newly added features.

This module tests:
- Icon handling
- Dry-run for create and fix commands
- Universal binary detection
- Progress spinner
- Info.plist template expansions (min_system_version, NSHighResolutionCapable)
"""

import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from macbundler import (
    Bundle,
    DylibBundler,
    ProgressSpinner,
    ValidationError,
    get_binary_architectures,
    get_binary_info,
    is_universal_binary,
)

# Mach-O 64-bit magic number for creating fake executables
MACHO_MAGIC_64 = b"\xcf\xfa\xed\xfe"


def create_fake_macho(path: Path, executable: bool = True) -> None:
    """Create a fake Mach-O file for testing."""
    path.write_bytes(MACHO_MAGIC_64 + b"\x00" * 100)
    if executable:
        path.chmod(0o755)


class TestIconHandling:
    """Tests for icon handling in Bundle."""

    def test_bundle_init_with_icon(self, tmp_path: Path) -> None:
        """Test Bundle initialization with icon parameter."""
        exe = tmp_path / "myapp"
        create_fake_macho(exe)
        icon = tmp_path / "myapp.icns"
        icon.write_bytes(b"fake icon data")

        bundle = Bundle(exe, icon=icon)
        assert bundle.icon == icon
        assert bundle._icon_filename == "myapp.icns"

    def test_bundle_init_without_icon(self, tmp_path: Path) -> None:
        """Test Bundle initialization without icon parameter."""
        exe = tmp_path / "myapp"
        create_fake_macho(exe)

        bundle = Bundle(exe)
        assert bundle.icon is None
        assert bundle._icon_filename == "app.icns"

    def test_create_resources_with_icon(self, tmp_path: Path) -> None:
        """Test that icon is copied to Resources folder."""
        exe = tmp_path / "myapp"
        create_fake_macho(exe)

        icon = tmp_path / "myapp.icns"
        icon.write_bytes(b"fake icon data")

        bundle = Bundle(exe, icon=icon, codesign=False)
        # Create bundle structure manually
        bundle.macos.mkdir(parents=True)
        bundle.create_resources()

        # Check icon was copied
        dest_icon = bundle.resources.path / "myapp.icns"
        assert dest_icon.exists()
        assert dest_icon.read_bytes() == b"fake icon data"

    def test_create_resources_icon_not_found(self, tmp_path: Path) -> None:
        """Test error when icon file doesn't exist."""
        exe = tmp_path / "myapp"
        create_fake_macho(exe)

        nonexistent_icon = tmp_path / "nonexistent.icns"
        bundle = Bundle(exe, icon=nonexistent_icon, codesign=False)
        bundle.macos.mkdir(parents=True)

        with pytest.raises(ValidationError, match="File does not exist"):
            bundle.create_resources()

    def test_info_plist_contains_icon_filename(self, tmp_path: Path) -> None:
        """Test that Info.plist contains the icon filename."""
        exe = tmp_path / "myapp"
        create_fake_macho(exe)
        icon = tmp_path / "custom_icon.icns"
        icon.write_bytes(b"fake icon")

        bundle = Bundle(exe, icon=icon, codesign=False)
        bundle.macos.mkdir(parents=True)
        bundle.create_info_plist()

        content = bundle.info_plist.read_text()
        assert "custom_icon.icns" in content


class TestDryRunCreate:
    """Tests for dry-run in create command."""

    def test_bundle_dry_run_no_files_created(self, tmp_path: Path) -> None:
        """Test that dry-run doesn't create any files."""
        exe = tmp_path / "myapp"
        create_fake_macho(exe)

        bundle = Bundle(exe, dry_run=True, codesign=False)
        bundle.create()

        # Bundle directory should not exist
        assert not bundle.bundle.exists()

    def test_bundle_dry_run_logs_actions(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that dry-run logs what would be done."""
        import logging

        caplog.set_level(logging.INFO)

        exe = tmp_path / "myapp"
        create_fake_macho(exe)

        bundle = Bundle(exe, dry_run=True, codesign=False)
        bundle.create()

        # Check for dry-run log messages
        assert any("[DRY RUN]" in record.message for record in caplog.records)


class TestDryRunFix:
    """Tests for dry-run in fix command."""

    def test_dylibbundler_dry_run_no_files_created(
        self, tmp_path: Path
    ) -> None:
        """Test that dry-run doesn't create any files."""
        exe = tmp_path / "myapp"
        exe.touch()
        exe.chmod(0o755)

        dest = tmp_path / "libs"

        bundler = DylibBundler(
            dest_dir=dest,
            files_to_fix=[exe],
            create_dir=True,
            dry_run=True,
            codesign=False,
        )
        bundler.process_collected_deps()

        # Destination directory should not exist
        assert not dest.exists()

    def test_dylibbundler_dry_run_logs_actions(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that dry-run logs what would be done."""
        import logging

        caplog.set_level(logging.INFO)

        exe = tmp_path / "myapp"
        exe.touch()
        exe.chmod(0o755)

        dest = tmp_path / "libs"

        bundler = DylibBundler(
            dest_dir=dest,
            files_to_fix=[exe],
            create_dir=True,
            dry_run=True,
            codesign=False,
        )
        bundler.process_collected_deps()

        # Check for dry-run log messages
        assert any("[DRY RUN]" in record.message for record in caplog.records)


class TestUniversalBinaryDetection:
    """Tests for universal binary detection functions."""

    def test_get_binary_architectures_nonexistent(self) -> None:
        """Test with nonexistent file."""
        result = get_binary_architectures("/nonexistent/path")
        assert result == []

    def test_get_binary_architectures_not_macho(self, tmp_path: Path) -> None:
        """Test with non-Mach-O file."""
        text_file = tmp_path / "text.txt"
        text_file.write_text("not a binary")

        result = get_binary_architectures(text_file)
        assert result == []

    def test_get_binary_architectures_with_system_binary(self) -> None:
        """Test with a known system binary."""
        # /bin/ls should exist on macOS
        result = get_binary_architectures("/bin/ls")
        # Should return at least one architecture
        assert len(result) >= 1
        # Should be a valid architecture name
        assert all(isinstance(arch, str) for arch in result)

    def test_is_universal_binary_single_arch(self) -> None:
        """Test is_universal_binary with single architecture."""
        with patch(
            "macbundler.get_binary_architectures", return_value=["arm64"]
        ):
            result = is_universal_binary("/fake/path")
            assert result is False

    def test_is_universal_binary_multi_arch(self) -> None:
        """Test is_universal_binary with multiple architectures."""
        with patch(
            "macbundler.get_binary_architectures",
            return_value=["x86_64", "arm64"],
        ):
            result = is_universal_binary("/fake/path")
            assert result is True

    def test_get_binary_info(self) -> None:
        """Test get_binary_info returns expected structure."""
        with patch(
            "macbundler.get_binary_architectures",
            return_value=["x86_64", "arm64"],
        ):
            result = get_binary_info("/fake/path")
            assert result["architectures"] == ["x86_64", "arm64"]
            assert result["is_universal"] is True
            assert result["is_arm"] is True
            assert result["is_intel"] is True

    def test_get_binary_info_arm_only(self) -> None:
        """Test get_binary_info with ARM-only binary."""
        with patch(
            "macbundler.get_binary_architectures", return_value=["arm64"]
        ):
            result = get_binary_info("/fake/path")
            assert result["is_universal"] is False
            assert result["is_arm"] is True
            assert result["is_intel"] is False


class TestProgressSpinner:
    """Tests for ProgressSpinner class."""

    def test_spinner_starts_and_stops(self) -> None:
        """Test that spinner can start and stop."""
        spinner = ProgressSpinner("Testing")
        spinner.start()
        time.sleep(0.2)  # Let it spin briefly
        spinner.stop()

        # Thread should be stopped
        assert spinner._stop_event.is_set()

    def test_spinner_context_manager(self) -> None:
        """Test spinner as context manager."""
        with ProgressSpinner("Testing") as spinner:
            assert spinner._thread is not None
            assert spinner._thread.is_alive()
            time.sleep(0.1)

        # After context exit, thread should be stopped
        assert spinner._stop_event.is_set()

    def test_spinner_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that spinner produces output."""
        with ProgressSpinner("Working"):
            time.sleep(0.3)

        captured = capsys.readouterr()
        # Should contain the message and "done"
        assert "Working" in captured.out
        assert "done" in captured.out


class TestMinSystemVersion:
    """Tests for minimum system version in Info.plist."""

    def test_default_min_system_version(self, tmp_path: Path) -> None:
        """Test default minimum system version."""
        exe = tmp_path / "myapp"
        create_fake_macho(exe)

        bundle = Bundle(exe, codesign=False)
        assert bundle.min_system_version == "10.13"

    def test_custom_min_system_version(self, tmp_path: Path) -> None:
        """Test custom minimum system version."""
        exe = tmp_path / "myapp"
        create_fake_macho(exe)

        bundle = Bundle(exe, min_system_version="11.0", codesign=False)
        assert bundle.min_system_version == "11.0"

    def test_info_plist_contains_min_system_version(
        self, tmp_path: Path
    ) -> None:
        """Test that Info.plist contains LSMinimumSystemVersion."""
        exe = tmp_path / "myapp"
        create_fake_macho(exe)

        bundle = Bundle(exe, min_system_version="12.0", codesign=False)
        bundle.macos.mkdir(parents=True)
        bundle.create_info_plist()

        content = bundle.info_plist.read_text()
        assert "LSMinimumSystemVersion" in content
        assert "12.0" in content


class TestCLINewOptions:
    """Tests for new CLI options."""

    def test_create_help_shows_new_options(self) -> None:
        """Test that create help shows new options."""
        result = subprocess.run(
            ["python", "-m", "macbundler", "create", "--help"],
            capture_output=True,
            text=True,
        )
        assert "--icon" in result.stdout
        assert "--min-system-version" in result.stdout
        assert "--dry-run" in result.stdout

    def test_fix_help_shows_dry_run(self) -> None:
        """Test that fix help shows --dry-run option."""
        result = subprocess.run(
            ["python", "-m", "macbundler", "fix", "--help"],
            capture_output=True,
            text=True,
        )
        assert "--dry-run" in result.stdout


class TestNSHighResolutionCapable:
    """Tests for NSHighResolutionCapable in Info.plist."""

    def test_info_plist_contains_high_resolution_capable(
        self, tmp_path: Path
    ) -> None:
        """Test that Info.plist contains NSHighResolutionCapable."""
        exe = tmp_path / "myapp"
        create_fake_macho(exe)

        bundle = Bundle(exe, codesign=False)
        bundle.macos.mkdir(parents=True)
        bundle.create_info_plist()

        content = bundle.info_plist.read_text()
        assert "NSHighResolutionCapable" in content
        assert "<true/>" in content
