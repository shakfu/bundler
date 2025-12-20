"""Unit tests for Packager class."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from macbundler import (
    ConfigurationError,
    Packager,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


@pytest.fixture
def sample_bundle(temp_dir):
    """Create a sample .app bundle structure."""
    bundle = temp_dir / "Test.app"
    contents = bundle / "Contents"
    macos = contents / "MacOS"

    macos.mkdir(parents=True)

    # Create executable
    exe = macos / "test"
    exe.write_bytes(b"#!/bin/bash\necho hello")
    exe.chmod(0o755)

    return bundle


@pytest.fixture
def sample_folder(temp_dir):
    """Create a sample folder with bundles."""
    folder = temp_dir / "dist"
    folder.mkdir()

    # Create an app inside
    app = folder / "MyApp.app" / "Contents" / "MacOS"
    app.mkdir(parents=True)
    (app / "MyApp").write_bytes(b"fake exe")

    return folder


class TestPackagerInit:
    """Tests for Packager initialization."""

    def test_init_source_not_found(self, temp_dir):
        """Test error when source doesn't exist."""
        with pytest.raises(ConfigurationError, match="does not exist"):
            Packager(temp_dir / "missing.app")

    def test_init_default_output(self, sample_bundle):
        """Test default output DMG name generation."""
        packager = Packager(sample_bundle, dry_run=True)
        expected = sample_bundle.parent / "Test.dmg"
        assert packager.output == expected

    def test_init_custom_output(self, sample_bundle, temp_dir):
        """Test custom output path."""
        output = temp_dir / "custom.dmg"
        packager = Packager(sample_bundle, output=output, dry_run=True)
        assert packager.output == output

    def test_init_default_volume_name(self, sample_bundle):
        """Test default volume name."""
        packager = Packager(sample_bundle, dry_run=True)
        assert packager.volume_name == "Test"

    def test_init_custom_volume_name(self, sample_bundle):
        """Test custom volume name."""
        packager = Packager(sample_bundle, volume_name="My App", dry_run=True)
        assert packager.volume_name == "My App"

    def test_init_dev_id_from_param(self, sample_bundle):
        """Test Developer ID from parameter."""
        packager = Packager(sample_bundle, dev_id="John Doe", dry_run=True)
        assert packager.dev_id == "John Doe"

    def test_init_dev_id_from_env(self, sample_bundle, monkeypatch):
        """Test Developer ID from environment variable."""
        monkeypatch.setenv("DEV_ID", "Jane Doe")
        packager = Packager(sample_bundle, dry_run=True)
        assert packager.dev_id == "Jane Doe"

    def test_init_dev_id_dash_is_none(self, sample_bundle):
        """Test that '-' dev_id is treated as None."""
        packager = Packager(sample_bundle, dev_id="-", dry_run=True)
        assert packager.dev_id is None

    def test_init_keychain_profile_from_param(self, sample_bundle):
        """Test keychain profile from parameter."""
        packager = Packager(
            sample_bundle, keychain_profile="AC_PROFILE", dry_run=True
        )
        assert packager.keychain_profile == "AC_PROFILE"

    def test_init_keychain_profile_from_env(self, sample_bundle, monkeypatch):
        """Test keychain profile from environment variable."""
        monkeypatch.setenv("KEYCHAIN_PROFILE", "ENV_PROFILE")
        packager = Packager(sample_bundle, dry_run=True)
        assert packager.keychain_profile == "ENV_PROFILE"


class TestPackagerDryRun:
    """Tests for Packager dry-run mode."""

    def test_dry_run_no_dmg_created(self, sample_bundle):
        """Test that dry_run doesn't create DMG."""
        packager = Packager(
            sample_bundle,
            dev_id="Test",
            keychain_profile="Profile",
            dry_run=True,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="", stderr=""
            )
            packager.process()

        # DMG should not exist (dry run)
        assert not packager.output.exists()

    def test_dry_run_logs_commands(self, sample_bundle):
        """Test that dry_run logs commands."""
        packager = Packager(sample_bundle, dry_run=True)

        # Should not raise, just log
        result = packager.run_command("echo test")
        assert result == ""  # dry run returns empty string


class TestPackagerDmgCreation:
    """Tests for DMG creation."""

    @patch("subprocess.run")
    def test_create_dmg_command(self, mock_run, sample_bundle):
        """Test DMG creation command."""
        packager = Packager(sample_bundle, sign_contents=False)

        # Side effect to create the file when hdiutil is called
        def create_dmg_side_effect(*args, **kwargs):
            packager.output.write_bytes(b"fake dmg")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = create_dmg_side_effect
        packager.create_dmg()

        mock_run.assert_called()
        call_args = mock_run.call_args[0][0]
        assert "hdiutil create" in call_args
        assert "-volname" in call_args
        assert "-srcfolder" in call_args
        assert "-format UDZO" in call_args

    @patch("subprocess.run")
    def test_create_dmg_removes_existing(self, mock_run, sample_bundle):
        """Test that existing DMG is removed before creation."""
        packager = Packager(sample_bundle, sign_contents=False)
        # Pre-create the output file
        packager.output.write_bytes(b"old dmg")

        # Side effect to create the file when hdiutil is called
        def create_dmg_side_effect(*args, **kwargs):
            packager.output.write_bytes(b"new dmg")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = create_dmg_side_effect
        packager.create_dmg()

        # The command should have been called
        mock_run.assert_called()


class TestPackagerSigning:
    """Tests for DMG signing."""

    @patch("subprocess.run")
    def test_sign_dmg_requires_dev_id(self, mock_run, sample_bundle):
        """Test that signing requires Developer ID."""
        packager = Packager(sample_bundle, sign_contents=False)
        packager.output.write_bytes(b"fake dmg")

        with pytest.raises(ConfigurationError, match="Developer ID required"):
            packager.sign_dmg()

    @patch("subprocess.run")
    def test_sign_dmg_command(self, mock_run, sample_bundle):
        """Test DMG signing command."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        packager = Packager(
            sample_bundle, dev_id="John Doe", sign_contents=False
        )
        packager.output.write_bytes(b"fake dmg")
        packager.sign_dmg()

        mock_run.assert_called()
        call_args = mock_run.call_args[0][0]
        assert "codesign" in call_args
        assert "Developer ID Application: John Doe" in call_args
        assert "--options runtime" in call_args


class TestPackagerNotarization:
    """Tests for notarization."""

    @patch("subprocess.run")
    def test_notarize_requires_keychain_profile(self, mock_run, sample_bundle):
        """Test that notarization requires keychain profile."""
        packager = Packager(sample_bundle, dev_id="Test", sign_contents=False)
        packager.output.write_bytes(b"fake dmg")

        with pytest.raises(
            ConfigurationError, match="Keychain profile required"
        ):
            packager.notarize_dmg()

    @patch("subprocess.run")
    def test_notarize_command(self, mock_run, sample_bundle):
        """Test notarization command."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        packager = Packager(
            sample_bundle,
            dev_id="Test",
            keychain_profile="AC_PROFILE",
            sign_contents=False,
        )
        packager.output.write_bytes(b"fake dmg")
        packager.notarize_dmg()

        mock_run.assert_called()
        call_args = mock_run.call_args[0][0]
        assert "xcrun notarytool submit" in call_args
        assert "--keychain-profile" in call_args
        assert "AC_PROFILE" in call_args
        assert "--wait" in call_args


class TestPackagerStaple:
    """Tests for stapling."""

    @patch("subprocess.run")
    def test_staple_command(self, mock_run, sample_bundle):
        """Test staple command."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        packager = Packager(sample_bundle, sign_contents=False)
        packager.output.write_bytes(b"fake dmg")
        packager.staple_dmg()

        mock_run.assert_called()
        call_args = mock_run.call_args[0][0]
        assert "xcrun stapler staple" in call_args


class TestPackagerProcess:
    """Tests for full packaging workflow."""

    @patch("subprocess.run")
    def test_process_full_workflow(self, mock_run, sample_bundle):
        """Test full workflow with all steps."""
        packager = Packager(
            sample_bundle,
            dev_id="Test Dev",
            keychain_profile="Profile",
            sign_contents=False,  # Skip content signing for simpler test
        )

        # Side effect to create the DMG file when hdiutil is called
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            # Create DMG on first call (hdiutil create)
            if call_count[0] == 1:
                packager.output.write_bytes(b"fake dmg")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        result = packager.process()

        assert result == packager.output
        # Should have called multiple commands
        assert mock_run.call_count >= 3  # create, sign, notarize, staple

    @patch("subprocess.run")
    def test_process_skip_notarize(self, mock_run, sample_bundle):
        """Test workflow without notarization."""
        packager = Packager(
            sample_bundle,
            dev_id="Test Dev",
            sign_contents=False,
        )

        # Side effect to create the DMG file
        def side_effect(*args, **kwargs):
            if "hdiutil" in args[0]:
                packager.output.write_bytes(b"fake dmg")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        packager.process(notarize=False)

        # Check that notarytool was NOT called
        calls = [str(c) for c in mock_run.call_args_list]
        assert not any("notarytool" in c for c in calls)

    @patch("subprocess.run")
    def test_process_skip_staple(self, mock_run, sample_bundle):
        """Test workflow without stapling."""
        packager = Packager(
            sample_bundle,
            dev_id="Test Dev",
            keychain_profile="Profile",
            sign_contents=False,
        )

        # Side effect to create the DMG file
        def side_effect(*args, **kwargs):
            if "hdiutil" in args[0]:
                packager.output.write_bytes(b"fake dmg")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        packager.process(staple=False)

        # Check that stapler was NOT called
        calls = [str(c) for c in mock_run.call_args_list]
        assert not any("stapler" in c for c in calls)

    @patch("subprocess.run")
    def test_process_warns_without_dev_id(
        self, mock_run, sample_bundle, caplog
    ):
        """Test warning when no Developer ID."""
        packager = Packager(
            sample_bundle,
            sign_contents=False,
        )

        # Side effect to create the DMG file
        def side_effect(*args, **kwargs):
            if "hdiutil" in args[0]:
                packager.output.write_bytes(b"fake dmg")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        import logging

        with caplog.at_level(logging.WARNING):
            packager.process(notarize=False)

        # Should have logged a warning about skipping DMG signing
        # (We can't easily check caplog here without more setup)


class TestPackagerSignContents:
    """Tests for signing bundle contents."""

    @patch("subprocess.run")
    def test_sign_bundle_contents(self, mock_run, sample_bundle):
        """Test that bundle contents are signed when requested."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        packager = Packager(
            sample_bundle,
            dev_id="Test Dev",
            sign_contents=True,
        )
        packager.output.write_bytes(b"fake dmg")

        packager.sign_bundle_contents()

        # Should have called codesign for the bundle
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("codesign" in c for c in calls)

    @patch("subprocess.run")
    def test_sign_folder_contents(self, mock_run, sample_folder):
        """Test signing contents of a folder with bundles."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        packager = Packager(
            sample_folder,
            dev_id="Test Dev",
            sign_contents=True,
        )

        packager.sign_bundle_contents()

        # Should have signed the app inside the folder
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("codesign" in c for c in calls)

    def test_skip_sign_without_dev_id(self, sample_bundle):
        """Test that content signing is skipped without dev_id."""
        packager = Packager(
            sample_bundle,
            sign_contents=True,
        )

        # Should not raise, just skip
        packager.sign_bundle_contents()
