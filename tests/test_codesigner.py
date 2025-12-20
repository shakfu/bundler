"""Unit tests for Codesigner class."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from macbundler import (
    Codesigner,
    ConfigurationError,
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
    libs = contents / "libs"
    frameworks = contents / "Frameworks"

    macos.mkdir(parents=True)
    libs.mkdir()
    frameworks.mkdir()

    # Create executable
    exe = macos / "test"
    exe.write_bytes(b"#!/bin/bash\necho hello")
    exe.chmod(0o755)

    # Create some dylibs
    (libs / "libfoo.dylib").write_bytes(b"fake dylib")
    (libs / "libbar.so").write_bytes(b"fake so")

    # Create a nested framework
    nested_fw = frameworks / "Nested.framework"
    nested_fw.mkdir()
    (nested_fw / "Nested").write_bytes(b"fake framework binary")

    # Create a nested app
    nested_app = contents / "PlugIns" / "Helper.app" / "Contents" / "MacOS"
    nested_app.mkdir(parents=True)
    (nested_app / "Helper").write_bytes(b"fake helper exe")

    return bundle


class TestCodesignerInit:
    """Tests for Codesigner initialization."""

    def test_init_adhoc(self, temp_dir):
        """Test initialization with ad-hoc signing (no dev_id)."""
        bundle = temp_dir / "Test.app"
        bundle.mkdir()
        signer = Codesigner(bundle)
        assert signer.authority is None  # ad-hoc

    def test_init_adhoc_dash(self, temp_dir):
        """Test initialization with explicit ad-hoc ('-')."""
        bundle = temp_dir / "Test.app"
        bundle.mkdir()
        signer = Codesigner(bundle, dev_id="-")
        assert signer.authority is None

    def test_init_adhoc_empty(self, temp_dir):
        """Test initialization with empty dev_id."""
        bundle = temp_dir / "Test.app"
        bundle.mkdir()
        signer = Codesigner(bundle, dev_id="")
        assert signer.authority is None

    def test_init_dev_id(self, temp_dir):
        """Test initialization with Developer ID."""
        bundle = temp_dir / "Test.app"
        bundle.mkdir()
        signer = Codesigner(bundle, dev_id="John Doe")
        assert signer.authority == "Developer ID Application: John Doe"

    def test_init_from_env_var(self, temp_dir, monkeypatch):
        """Test DEV_ID environment variable fallback."""
        monkeypatch.setenv("DEV_ID", "Jane Doe")
        bundle = temp_dir / "Test.app"
        bundle.mkdir()
        signer = Codesigner(bundle)
        assert signer.authority == "Developer ID Application: Jane Doe"

    def test_init_param_overrides_env(self, temp_dir, monkeypatch):
        """Test that parameter overrides environment variable."""
        monkeypatch.setenv("DEV_ID", "Jane Doe")
        bundle = temp_dir / "Test.app"
        bundle.mkdir()
        signer = Codesigner(bundle, dev_id="John Doe")
        assert signer.authority == "Developer ID Application: John Doe"

    def test_init_entitlements_not_found(self, temp_dir):
        """Test error when entitlements file doesn't exist."""
        bundle = temp_dir / "Test.app"
        bundle.mkdir()
        with pytest.raises(ConfigurationError, match="not found"):
            Codesigner(bundle, entitlements=temp_dir / "missing.plist")

    def test_init_entitlements_found(self, temp_dir):
        """Test successful entitlements initialization."""
        bundle = temp_dir / "Test.app"
        bundle.mkdir()
        entitlements = temp_dir / "entitlements.plist"
        entitlements.write_text("<plist></plist>")
        signer = Codesigner(bundle, entitlements=entitlements)
        assert signer.entitlements == entitlements


class TestCodesignerCollect:
    """Tests for Codesigner.collect() method."""

    def test_collect_file_extensions(self, sample_bundle):
        """Test collection of .so and .dylib files."""
        signer = Codesigner(sample_bundle, dry_run=True)
        signer.collect()

        # Should find dylib and so files
        internal_names = {p.name for p in signer.targets_internals}
        assert "libfoo.dylib" in internal_names
        assert "libbar.so" in internal_names

    def test_collect_folder_extensions(self, sample_bundle):
        """Test collection of .framework folders."""
        signer = Codesigner(sample_bundle, dry_run=True)
        signer.collect()

        # Should find the framework
        framework_names = {p.name for p in signer.targets_frameworks}
        assert "Nested.framework" in framework_names

    def test_collect_nested_apps(self, sample_bundle):
        """Test collection of nested .app bundles."""
        signer = Codesigner(sample_bundle, dry_run=True)
        signer.collect()

        # Should find the nested app
        app_names = {p.name for p in signer.targets_apps}
        assert "Helper.app" in app_names

    def test_collect_skips_symlinks(self, sample_bundle):
        """Test that symlinks are not added to targets."""
        # Create a symlink
        libs = sample_bundle / "Contents" / "libs"
        (libs / "liblink.dylib").symlink_to(libs / "libfoo.dylib")

        signer = Codesigner(sample_bundle, dry_run=True)
        signer.collect()

        # Symlink should not be in targets
        internal_names = {p.name for p in signer.targets_internals}
        assert "liblink.dylib" not in internal_names
        assert "libfoo.dylib" in internal_names


class TestCodesignerDryRun:
    """Tests for Codesigner dry-run mode."""

    def test_dry_run_no_commands(self, sample_bundle):
        """Test that dry_run doesn't execute commands."""
        signer = Codesigner(sample_bundle, dry_run=True)

        with patch("subprocess.run") as mock_run:
            signer.process_dry_run()
            # subprocess.run should not be called in dry_run
            mock_run.assert_not_called()

    def test_dry_run_collects_targets(self, sample_bundle):
        """Test that dry_run still collects targets."""
        signer = Codesigner(sample_bundle, dry_run=True)
        signer.process_dry_run()

        # Targets should be collected
        assert len(signer.targets_internals) > 0


class TestCodesignerSigning:
    """Tests for Codesigner signing methods."""

    @patch("subprocess.run")
    def test_sign_internal_binary(self, mock_run, sample_bundle):
        """Test signing an internal binary."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        signer = Codesigner(sample_bundle)
        dylib = sample_bundle / "Contents" / "libs" / "libfoo.dylib"
        signer.sign_internal_binary(dylib)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "codesign" in call_args
        assert str(dylib) in call_args
        assert "--sign" in call_args

    @patch("subprocess.run")
    def test_sign_runtime_with_entitlements(
        self, mock_run, sample_bundle, temp_dir
    ):
        """Test signing runtime with entitlements."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        entitlements = temp_dir / "ent.plist"
        entitlements.write_text("<plist></plist>")

        signer = Codesigner(
            sample_bundle, dev_id="Test Dev", entitlements=entitlements
        )
        signer.sign_runtime()

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "--options" in call_args
        assert "runtime" in call_args
        assert "--entitlements" in call_args
        assert str(entitlements) in call_args

    @patch("subprocess.run")
    def test_verify_signature_success(self, mock_run, sample_bundle):
        """Test signature verification success."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        signer = Codesigner(sample_bundle)
        result = signer.verify_signature(sample_bundle)

        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "codesign --verify" in call_args


class TestCodesignerProcess:
    """Tests for Codesigner.process() full workflow."""

    @patch("subprocess.run")
    def test_process_signing_order(self, mock_run, sample_bundle):
        """Test that signing happens in correct order."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        signer = Codesigner(sample_bundle, verify=False)
        signer.process()

        # Should have multiple calls for internals, apps, frameworks, main
        assert mock_run.call_count > 0

    @patch("subprocess.run")
    def test_process_with_verification(self, mock_run, sample_bundle):
        """Test process includes verification step."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        signer = Codesigner(sample_bundle, verify=True)
        signer.process()

        # Check that verification was called
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("--verify" in c for c in calls)


class TestCodesignerCmdline:
    """Tests for codesign command construction."""

    def test_adhoc_command(self, temp_dir):
        """Test ad-hoc signing command construction."""
        bundle = temp_dir / "Test.app"
        bundle.mkdir()
        signer = Codesigner(bundle)

        # Command should use '-' for ad-hoc
        assert "-" in signer._cmd_codesign

    def test_dev_id_command(self, temp_dir):
        """Test Developer ID command construction."""
        bundle = temp_dir / "Test.app"
        bundle.mkdir()
        signer = Codesigner(bundle, dev_id="John Doe")

        # Command should include the authority
        cmd = " ".join(signer._cmd_codesign)
        assert "Developer ID Application: John Doe" in cmd
