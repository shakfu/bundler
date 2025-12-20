"""Tests for security validation features.

This module tests:
- File validation (validate_file)
- Developer ID validation (validate_developer_id)
- Mach-O detection (is_valid_macho)
"""

from pathlib import Path

import pytest

from macbundler import (
    Codesigner,
    Packager,
    ValidationError,
    is_valid_macho,
    validate_developer_id,
    validate_file,
)

# Mach-O magic numbers for testing
MACHO_MAGIC_64 = b"\xcf\xfa\xed\xfe"  # MH_CIGAM_64
MACHO_MAGIC_FAT = b"\xca\xfe\xba\xbe"  # FAT_MAGIC (universal)


class TestValidateFile:
    """Tests for validate_file function."""

    def test_validate_nonexistent_file(self, tmp_path: Path) -> None:
        """Test validation fails for nonexistent file."""
        nonexistent = tmp_path / "nonexistent"
        with pytest.raises(ValidationError, match="does not exist"):
            validate_file(nonexistent)

    def test_validate_empty_file(self, tmp_path: Path) -> None:
        """Test validation fails for empty file."""
        empty = tmp_path / "empty"
        empty.touch()
        with pytest.raises(ValidationError, match="empty"):
            validate_file(empty)

    def test_validate_symlink(self, tmp_path: Path) -> None:
        """Test validation fails for symbolic links."""
        target = tmp_path / "target"
        target.write_bytes(b"content")
        link = tmp_path / "link"
        link.symlink_to(target)
        with pytest.raises(ValidationError, match="symbolic link"):
            validate_file(link)

    def test_validate_directory(self, tmp_path: Path) -> None:
        """Test validation fails for directories."""
        with pytest.raises(ValidationError, match="not a regular file"):
            validate_file(tmp_path)

    def test_validate_valid_file(self, tmp_path: Path) -> None:
        """Test validation passes for valid file."""
        valid = tmp_path / "valid"
        valid.write_bytes(b"some content")
        # Should not raise
        validate_file(valid)

    def test_validate_file_too_large(self, tmp_path: Path) -> None:
        """Test validation fails for files exceeding max size."""
        large = tmp_path / "large"
        large.write_bytes(b"x" * 100)
        with pytest.raises(ValidationError, match="exceeds maximum size"):
            validate_file(large, max_size=50)

    def test_validate_executable_check_pass(self, tmp_path: Path) -> None:
        """Test executable check passes for executable file."""
        exe = tmp_path / "exe"
        exe.write_bytes(b"content")
        exe.chmod(0o755)
        # Should not raise
        validate_file(exe, check_executable=True)

    def test_validate_executable_check_fail(self, tmp_path: Path) -> None:
        """Test executable check fails for non-executable file."""
        non_exe = tmp_path / "non_exe"
        non_exe.write_bytes(b"content")
        non_exe.chmod(0o644)
        with pytest.raises(ValidationError, match="not executable"):
            validate_file(non_exe, check_executable=True)

    def test_validate_macho_check_pass(self, tmp_path: Path) -> None:
        """Test Mach-O check passes for valid Mach-O file."""
        macho = tmp_path / "macho"
        macho.write_bytes(MACHO_MAGIC_64 + b"\x00" * 100)
        # Should not raise
        validate_file(macho, check_macho=True)

    def test_validate_macho_check_fail(self, tmp_path: Path) -> None:
        """Test Mach-O check fails for non-Mach-O file."""
        non_macho = tmp_path / "non_macho"
        non_macho.write_bytes(b"not a mach-o binary")
        with pytest.raises(ValidationError, match="not a valid Mach-O"):
            validate_file(non_macho, check_macho=True)

    def test_validate_universal_binary(self, tmp_path: Path) -> None:
        """Test Mach-O check passes for universal binary."""
        universal = tmp_path / "universal"
        universal.write_bytes(MACHO_MAGIC_FAT + b"\x00" * 100)
        # Should not raise
        validate_file(universal, check_macho=True)


class TestValidateDeveloperId:
    """Tests for validate_developer_id function."""

    def test_validate_empty_dev_id(self) -> None:
        """Test validation fails for empty Developer ID."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_developer_id("")

    def test_validate_whitespace_dev_id(self) -> None:
        """Test validation fails for whitespace-only Developer ID."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_developer_id("   ")

    def test_validate_short_dev_id(self) -> None:
        """Test validation fails for too short Developer ID."""
        with pytest.raises(ValidationError, match="too short"):
            validate_developer_id("A")

    def test_validate_long_dev_id(self) -> None:
        """Test validation fails for too long Developer ID."""
        long_id = "A" * 101
        with pytest.raises(ValidationError, match="too long"):
            validate_developer_id(long_id)

    def test_validate_valid_name_only(self) -> None:
        """Test validation passes for name only."""
        # Should not raise
        validate_developer_id("John Doe")

    def test_validate_valid_name_with_team_id(self) -> None:
        """Test validation passes for name with Team ID."""
        # Should not raise
        validate_developer_id("John Doe (ABCD123456)")

    def test_validate_name_with_special_chars(self) -> None:
        """Test validation passes for name with allowed special chars."""
        # Should not raise
        validate_developer_id("John O'Brien-Smith, Jr.")

    def test_validate_invalid_team_id_length(self) -> None:
        """Test validation fails for invalid Team ID length."""
        with pytest.raises(ValidationError, match="invalid format"):
            validate_developer_id("John Doe (ABC)")  # Too short

    def test_validate_invalid_team_id_chars(self) -> None:
        """Test validation fails for invalid Team ID characters."""
        with pytest.raises(ValidationError, match="invalid format"):
            validate_developer_id("John Doe (abcd123456)")  # Lowercase

    def test_validate_invalid_start_char(self) -> None:
        """Test validation fails for name not starting with letter."""
        with pytest.raises(ValidationError, match="invalid format"):
            validate_developer_id("123 Company")

    def test_validate_company_name(self) -> None:
        """Test validation passes for company names."""
        # Should not raise
        validate_developer_id("Acme Corporation (1234567890)")

    def test_validate_hyphenated_name(self) -> None:
        """Test validation passes for hyphenated names."""
        # Should not raise - hyphens are allowed
        validate_developer_id("Jean-Pierre Dupont")


class TestIsValidMacho:
    """Tests for is_valid_macho function."""

    def test_valid_macho_64bit(self, tmp_path: Path) -> None:
        """Test detection of 64-bit Mach-O."""
        macho = tmp_path / "macho64"
        macho.write_bytes(MACHO_MAGIC_64 + b"\x00" * 100)
        assert is_valid_macho(macho) is True

    def test_valid_macho_fat(self, tmp_path: Path) -> None:
        """Test detection of fat/universal Mach-O."""
        fat = tmp_path / "fat"
        fat.write_bytes(MACHO_MAGIC_FAT + b"\x00" * 100)
        assert is_valid_macho(fat) is True

    def test_invalid_macho(self, tmp_path: Path) -> None:
        """Test detection of non-Mach-O file."""
        text = tmp_path / "text"
        text.write_bytes(b"Hello, world!")
        assert is_valid_macho(text) is False

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Test with nonexistent file."""
        nonexistent = tmp_path / "nonexistent"
        assert is_valid_macho(nonexistent) is False

    def test_directory(self, tmp_path: Path) -> None:
        """Test with directory."""
        assert is_valid_macho(tmp_path) is False


class TestCodesignerValidation:
    """Tests for Developer ID validation in Codesigner."""

    def test_codesigner_valid_dev_id(self, tmp_path: Path) -> None:
        """Test Codesigner accepts valid Developer ID."""
        bundle = tmp_path / "Test.app"
        bundle.mkdir()
        # Should not raise
        signer = Codesigner(bundle, dev_id="John Doe (ABCD123456)")
        assert (
            signer.authority
            == "Developer ID Application: John Doe (ABCD123456)"
        )

    def test_codesigner_invalid_dev_id(self, tmp_path: Path) -> None:
        """Test Codesigner rejects invalid Developer ID."""
        bundle = tmp_path / "Test.app"
        bundle.mkdir()
        with pytest.raises(ValidationError, match="invalid format"):
            Codesigner(bundle, dev_id="123InvalidName")

    def test_codesigner_adhoc_skips_validation(self, tmp_path: Path) -> None:
        """Test Codesigner skips validation for ad-hoc signing."""
        bundle = tmp_path / "Test.app"
        bundle.mkdir()
        # Should not raise (ad-hoc signing)
        signer = Codesigner(bundle, dev_id="-")
        assert signer.authority is None

    def test_codesigner_none_dev_id_skips_validation(
        self, tmp_path: Path
    ) -> None:
        """Test Codesigner skips validation when dev_id is None."""
        bundle = tmp_path / "Test.app"
        bundle.mkdir()
        # Should not raise
        signer = Codesigner(bundle, dev_id=None)
        assert signer.authority is None


class TestPackagerValidation:
    """Tests for Developer ID validation in Packager."""

    def test_packager_valid_dev_id(self, tmp_path: Path) -> None:
        """Test Packager accepts valid Developer ID."""
        source = tmp_path / "Test.app"
        source.mkdir()
        # Should not raise
        packager = Packager(source, dev_id="John Doe (ABCD123456)")
        assert packager.dev_id == "John Doe (ABCD123456)"

    def test_packager_invalid_dev_id(self, tmp_path: Path) -> None:
        """Test Packager rejects invalid Developer ID."""
        source = tmp_path / "Test.app"
        source.mkdir()
        with pytest.raises(ValidationError, match="invalid format"):
            Packager(source, dev_id="123InvalidName")

    def test_packager_dash_dev_id_skips_validation(
        self, tmp_path: Path
    ) -> None:
        """Test Packager skips validation for '-' dev_id."""
        source = tmp_path / "Test.app"
        source.mkdir()
        # Should not raise
        packager = Packager(source, dev_id="-")
        assert packager.dev_id is None
