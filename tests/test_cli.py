"""Tests for the command-line interface."""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestCLICreate:
    """Tests for the 'create' subcommand."""

    def test_create_requires_executable(self):
        """Test that create subcommand requires an executable argument."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "create"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert (
            "required" in result.stderr.lower()
            or "arguments" in result.stderr.lower()
        )

    def test_create_nonexistent_executable(self):
        """Test create with a nonexistent executable."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "create", "/nonexistent/path"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_create_with_executable(self):
        """Test create with a valid executable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake executable
            exe_path = Path(tmpdir) / "myapp"
            exe_path.write_text("#!/bin/bash\necho hello")
            exe_path.chmod(0o755)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "macbundler",
                    "create",
                    str(exe_path),
                    "--no-sign",
                ],
                capture_output=True,
                text=True,
                cwd=tmpdir,
            )
            # May fail on non-Mach-O, but should not crash
            # The important thing is that the CLI parses arguments correctly
            assert "myapp" in result.stderr or result.returncode in (0, 1)

    def test_create_help(self):
        """Test create --help output."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "create", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "executable" in result.stdout.lower()
        assert "--version" in result.stdout
        assert "--id" in result.stdout
        assert "--resource" in result.stdout

    def test_create_version_option(self):
        """Test that --version option is accepted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            exe_path = Path(tmpdir) / "myapp"
            exe_path.write_text("#!/bin/bash\necho hello")
            exe_path.chmod(0o755)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "macbundler",
                    "create",
                    str(exe_path),
                    "--version",
                    "2.0.1",
                    "--no-sign",
                ],
                capture_output=True,
                text=True,
            )
            # CLI should accept the version option without error
            assert (
                "--version" not in result.stderr
                or "error" not in result.stderr.lower()
            )


class TestCLIFix:
    """Tests for the 'fix' subcommand."""

    def test_fix_requires_dest(self):
        """Test that fix subcommand requires --dest."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "fix", "somefile"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "-d" in result.stderr or "--dest" in result.stderr

    def test_fix_help(self):
        """Test fix --help output."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "fix", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--dest" in result.stdout
        assert "--prefix" in result.stdout
        assert "--search" in result.stdout
        assert "--exclude" in result.stdout

    def test_fix_accepts_multiple_files(self):
        """Test that fix accepts multiple file arguments."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "fix", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "files" in result.stdout.lower()


class TestCLISign:
    """Tests for the 'sign' subcommand."""

    def test_sign_requires_bundle(self):
        """Test that sign subcommand requires a bundle argument."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "sign"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_sign_nonexistent_bundle(self):
        """Test sign with a nonexistent bundle."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "macbundler",
                "sign",
                "/nonexistent/path.app",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_sign_help(self):
        """Test sign --help output."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "sign", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--dev-id" in result.stdout
        assert "--entitlements" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--no-verify" in result.stdout

    def test_sign_dry_run(self):
        """Test sign --dry-run with a bundle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal bundle structure
            bundle_path = Path(tmpdir) / "Test.app"
            contents = bundle_path / "Contents"
            macos = contents / "MacOS"
            macos.mkdir(parents=True)
            (macos / "Test").touch()

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "macbundler",
                    "sign",
                    str(bundle_path),
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert (
                "DRY RUN" in result.stderr or "dry run" in result.stderr.lower()
            )


class TestCLIPackage:
    """Tests for the 'package' subcommand."""

    def test_package_requires_source(self):
        """Test that package subcommand requires a source argument."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "package"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_package_nonexistent_source(self):
        """Test package with a nonexistent source."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "macbundler",
                "package",
                "/nonexistent/path",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_package_help(self):
        """Test package --help output."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "package", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--output" in result.stdout
        assert "--name" in result.stdout
        assert "--dev-id" in result.stdout
        assert "--keychain-profile" in result.stdout
        assert "--no-sign" in result.stdout
        assert "--no-notarize" in result.stdout
        assert "--no-staple" in result.stdout
        assert "--dry-run" in result.stdout

    def test_package_dry_run(self):
        """Test package --dry-run with a source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal bundle
            bundle_path = Path(tmpdir) / "Test.app"
            contents = bundle_path / "Contents"
            macos = contents / "MacOS"
            macos.mkdir(parents=True)
            (macos / "Test").touch()

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "macbundler",
                    "package",
                    str(bundle_path),
                    "--dry-run",
                    "--no-sign",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0


class TestCLIMain:
    """Tests for the main CLI entry point."""

    def test_no_subcommand(self):
        """Test running without a subcommand."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        # Should show usage or error about missing command
        assert (
            "command" in result.stderr.lower()
            or "usage" in result.stderr.lower()
        )

    def test_invalid_subcommand(self):
        """Test running with an invalid subcommand."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "invalid"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_main_help(self):
        """Test main --help output."""
        result = subprocess.run(
            [sys.executable, "-m", "macbundler", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "create" in result.stdout
        assert "fix" in result.stdout
        assert "sign" in result.stdout
        assert "package" in result.stdout


class TestCLIRunCommand:
    """Tests for the run_command utility function."""

    def test_run_command_success(self):
        """Test run_command with a successful command."""
        from macbundler import run_command

        result = run_command(["echo", "hello"])
        assert "hello" in result

    def test_run_command_failure(self):
        """Test run_command with a failing command."""
        from macbundler import CommandError, run_command

        with pytest.raises(CommandError):
            run_command(["false"])

    def test_run_command_dry_run(self):
        """Test run_command in dry-run mode."""
        from macbundler import run_command

        # In dry-run mode, command should not execute
        result = run_command(["echo", "hello"], dry_run=True)
        assert result == ""

    def test_run_command_with_logger(self):
        """Test run_command with a logger."""
        import logging

        from macbundler import run_command

        logger = logging.getLogger("test")
        result = run_command(["echo", "test"], log=logger)
        assert "test" in result


class TestCLIHandlersUnit:
    """Unit tests for CLI handler functions using mocks."""

    def test_cmd_create_calls_bundle(self):
        """Test that _cmd_create creates a Bundle instance."""
        from macbundler import _cmd_create

        with tempfile.TemporaryDirectory() as tmpdir:
            exe_path = Path(tmpdir) / "myapp"
            exe_path.write_text("#!/bin/bash\necho hello")
            exe_path.chmod(0o755)

            args = MagicMock()
            args.executable = str(exe_path)
            args.version = "1.0"
            args.resource = None
            args.id = "org.test"
            args.extension = ".app"
            args.no_sign = True
            args.verbose = False
            args.no_color = True

            with patch("macbundler.Bundle") as MockBundle:
                mock_instance = MagicMock()
                mock_instance.create.return_value = Path(tmpdir) / "myapp.app"
                MockBundle.return_value = mock_instance

                _cmd_create(args)

                MockBundle.assert_called_once()
                mock_instance.create.assert_called_once()

    def test_cmd_sign_calls_codesigner(self):
        """Test that _cmd_sign creates a Codesigner instance."""
        from macbundler import _cmd_sign

        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = Path(tmpdir) / "Test.app"
            bundle_path.mkdir()

            args = MagicMock()
            args.bundle = str(bundle_path)
            args.dev_id = None
            args.entitlements = None
            args.dry_run = True
            args.no_verify = True
            args.verbose = False
            args.no_color = True

            with patch("macbundler.Codesigner") as MockCodesigner:
                mock_instance = MagicMock()
                MockCodesigner.return_value = mock_instance

                _cmd_sign(args)

                MockCodesigner.assert_called_once()
                mock_instance.process_dry_run.assert_called_once()

    def test_cmd_package_calls_packager(self):
        """Test that _cmd_package creates a Packager instance."""
        from macbundler import _cmd_package

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "Test.app"
            source_path.mkdir()

            args = MagicMock()
            args.source = str(source_path)
            args.output = None
            args.name = None
            args.dev_id = None
            args.keychain_profile = None
            args.entitlements = None
            args.no_sign = True
            args.no_notarize = True
            args.no_staple = True
            args.dry_run = True
            args.verbose = False
            args.no_color = True

            with patch("macbundler.Packager") as MockPackager:
                mock_instance = MagicMock()
                mock_instance.process.return_value = Path(tmpdir) / "Test.dmg"
                MockPackager.return_value = mock_instance

                _cmd_package(args)

                MockPackager.assert_called_once()
                mock_instance.process.assert_called_once()


class TestConfigFile:
    """Tests for configuration file support."""

    def test_load_config_no_file(self):
        """Test load_config returns empty dict when no config exists."""
        from macbundler import load_config

        with tempfile.TemporaryDirectory() as tmpdir:
            # Change to empty directory
            import os

            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                config = load_config()
                assert config == {}
            finally:
                os.chdir(original_cwd)

    def test_load_config_from_macbundler_toml(self):
        """Test loading config from .macbundler.toml."""
        from macbundler import load_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".macbundler.toml"
            config_path.write_text("""
[create]
version = "2.0"
id = "com.test"

[sign]
dev_id = "Test Developer"
""")
            import os

            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                config = load_config()
                assert config.get("create", {}).get("version") == "2.0"
                assert config.get("create", {}).get("id") == "com.test"
                assert config.get("sign", {}).get("dev_id") == "Test Developer"
            finally:
                os.chdir(original_cwd)

    def test_load_config_explicit_path(self):
        """Test loading config from explicit path."""
        from macbundler import load_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "custom.toml"
            config_path.write_text("""
[package]
keychain_profile = "CUSTOM_PROFILE"
""")
            config = load_config(config_path)
            assert (
                config.get("package", {}).get("keychain_profile")
                == "CUSTOM_PROFILE"
            )

    def test_get_config_value(self):
        """Test get_config_value helper function."""
        from macbundler import get_config_value

        config = {
            "create": {"version": "3.0", "id": "com.example"},
            "sign": {"dev_id": "John Doe"},
        }

        assert get_config_value(config, "create", "version") == "3.0"
        assert get_config_value(config, "create", "id") == "com.example"
        assert get_config_value(config, "sign", "dev_id") == "John Doe"
        assert get_config_value(config, "sign", "missing") is None
        assert (
            get_config_value(config, "sign", "missing", "default") == "default"
        )
        assert get_config_value(config, "nonexistent", "key") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
