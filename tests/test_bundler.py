"""Unit tests for Bundle and BundleFolder classes."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import macbundler
from macbundler import (
    INFO_PLIST_TMPL,
    Bundle,
    BundleFolder,
    FileError,
    make_bundle,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


@pytest.fixture
def sample_executable(temp_dir):
    """Create a sample executable file."""
    exe_path = temp_dir / "test_app"
    exe_path.write_bytes(b"#!/bin/bash\necho 'hello'")
    exe_path.chmod(0o755)
    return exe_path


class TestBundleFolder:
    """Tests for BundleFolder class."""

    def test_init(self, temp_dir):
        """Test BundleFolder initialization."""
        folder = BundleFolder(temp_dir / "TestFolder")
        assert folder.path == temp_dir / "TestFolder"

    def test_create(self, temp_dir):
        """Test creating a bundle folder."""
        folder = BundleFolder(temp_dir / "TestFolder")
        folder.create()
        assert folder.path.exists()
        assert folder.path.is_dir()

    def test_create_nested(self, temp_dir):
        """Test creating nested bundle folders."""
        folder = BundleFolder(temp_dir / "Parent" / "Child" / "TestFolder")
        folder.create()
        assert folder.path.exists()
        assert folder.path.is_dir()

    def test_create_existing(self, temp_dir):
        """Test creating a folder that already exists."""
        folder_path = temp_dir / "ExistingFolder"
        folder_path.mkdir()
        folder = BundleFolder(folder_path)
        folder.create()  # Should not raise
        assert folder.path.exists()

    def test_create_file_error(self, temp_dir):
        """Test creating a folder where a file exists."""
        file_path = temp_dir / "file_not_dir"
        file_path.touch()
        folder = BundleFolder(file_path)
        with pytest.raises(FileError):
            folder.create()

    def test_copy(self, temp_dir):
        """Test copying content to bundle folder."""
        # Create source directory with content
        src_dir = temp_dir / "source"
        src_dir.mkdir()
        (src_dir / "file.txt").write_text("content")

        # Create destination folder
        dest = BundleFolder(temp_dir / "dest")
        dest.create()

        # Copy
        dest.copy(src_dir)

        assert (dest.path / "source" / "file.txt").exists()
        assert (dest.path / "source" / "file.txt").read_text() == "content"


class TestBundle:
    """Tests for Bundle class."""

    def test_init(self, sample_executable):
        """Test Bundle initialization."""
        bundle = Bundle(sample_executable)

        assert bundle.target == sample_executable
        assert bundle.version == "1.0"
        assert bundle.base_id == "org.me"
        assert bundle.extension == ".app"
        assert bundle.bundle == sample_executable.parent / "test_app.app"
        assert bundle.contents == bundle.bundle / "Contents"
        assert bundle.macos == bundle.contents / "MacOS"
        assert bundle.executable == bundle.macos / "test_app"

    def test_init_custom_options(self, sample_executable):
        """Test Bundle initialization with custom options."""
        bundle = Bundle(
            sample_executable,
            version="2.0",
            base_id="com.example",
            extension=".application",
        )

        assert bundle.version == "2.0"
        assert bundle.base_id == "com.example"
        assert bundle.extension == ".application"
        assert (
            bundle.bundle == sample_executable.parent / "test_app.application"
        )

    def test_create_executable(self, sample_executable):
        """Test creating bundle executable."""
        bundle = Bundle(sample_executable)
        bundle.macos.mkdir(parents=True)
        bundle.create_executable()

        assert bundle.executable.exists()
        assert (
            bundle.executable.stat().st_mode & 0o111
        )  # Has execute permissions

    def test_create_info_plist(self, sample_executable):
        """Test creating Info.plist."""
        bundle = Bundle(sample_executable, version="1.5")
        bundle.contents.mkdir(parents=True)
        bundle.create_info_plist()

        assert bundle.info_plist.exists()
        content = bundle.info_plist.read_text()
        assert "test_app" in content
        assert "org.me.test_app" in content
        assert "1.5" in content

    def test_create_pkg_info(self, sample_executable):
        """Test creating PkgInfo."""
        bundle = Bundle(sample_executable)
        bundle.contents.mkdir(parents=True)
        bundle.create_pkg_info()

        assert bundle.pkg_info.exists()
        assert bundle.pkg_info.read_text() == "APPL????"

    def test_create_resources(self, temp_dir, sample_executable):
        """Test creating Resources folder with content."""
        # Create a resource directory
        resource_dir = temp_dir / "resources"
        resource_dir.mkdir()
        (resource_dir / "data.txt").write_text("resource data")

        bundle = Bundle(sample_executable, add_to_resources=[str(resource_dir)])
        bundle.contents.mkdir(parents=True)
        bundle.create_resources()

        assert bundle.resources.path.exists()
        assert (bundle.resources.path / "resources" / "data.txt").exists()

    def test_create_resources_empty(self, sample_executable):
        """Test that Resources folder is not created when no resources."""
        bundle = Bundle(sample_executable)
        bundle.contents.mkdir(parents=True)
        bundle.create_resources()

        assert not bundle.resources.path.exists()

    @patch.object(macbundler.DylibBundler, "collect_dependencies")
    @patch.object(macbundler.DylibBundler, "collect_sub_dependencies")
    @patch.object(macbundler.DylibBundler, "process_collected_deps")
    def test_bundle_dependencies(
        self, mock_process, mock_sub, mock_collect, sample_executable
    ):
        """Test bundling dependencies (mocked DylibBundler)."""
        bundle = Bundle(sample_executable)
        bundle.macos.mkdir(parents=True)
        bundle.create_executable()
        bundle.bundle_dependencies()

        mock_collect.assert_called_once()
        mock_sub.assert_called_once()
        mock_process.assert_called_once()

    @patch.object(macbundler.DylibBundler, "collect_dependencies")
    @patch.object(macbundler.DylibBundler, "collect_sub_dependencies")
    @patch.object(macbundler.DylibBundler, "process_collected_deps")
    def test_create_full_bundle(
        self, mock_process, mock_sub, mock_collect, sample_executable
    ):
        """Test full bundle creation (mocked DylibBundler)."""
        bundle = Bundle(sample_executable, version="1.0")
        result = bundle.create()

        assert result == bundle.bundle
        assert bundle.bundle.exists()
        assert bundle.macos.exists()
        assert bundle.executable.exists()
        assert bundle.info_plist.exists()
        assert bundle.pkg_info.exists()


class TestMakeBundle:
    """Tests for make_bundle function."""

    @patch.object(macbundler.DylibBundler, "collect_dependencies")
    @patch.object(macbundler.DylibBundler, "collect_sub_dependencies")
    @patch.object(macbundler.DylibBundler, "process_collected_deps")
    def test_make_bundle(
        self, mock_process, mock_sub, mock_collect, sample_executable
    ):
        """Test make_bundle convenience function."""
        result = make_bundle(
            sample_executable, version="3.0", base_id="org.test"
        )

        assert result.exists()
        assert result.name == "test_app.app"

        # Check Info.plist content
        info_plist = result / "Contents" / "Info.plist"
        content = info_plist.read_text()
        assert "3.0" in content
        assert "org.test.test_app" in content


class TestInfoPlistTemplate:
    """Tests for INFO_PLIST_TMPL formatting."""

    def test_template_formatting(self):
        """Test that the template formats correctly."""
        result = INFO_PLIST_TMPL.format(
            executable="myapp",
            bundle_name="MyApp",
            bundle_identifier="com.example.myapp",
            bundle_version="1.2.3",
            versioned_bundle_name="MyApp 1.2.3",
        )

        assert "myapp" in result
        assert "MyApp" in result
        assert "com.example.myapp" in result
        assert "1.2.3" in result
        assert "MyApp 1.2.3" in result
        assert '<?xml version="1.0"' in result
        assert "<plist version=" in result
