"""Integration test that creates a real executable with dylib dependency and bundles it."""

import os
import subprocess
from pathlib import Path

import pytest

from macbundler import Bundle, DylibBundler


@pytest.fixture
def build_dir():
    """Create build directory for test artifacts."""
    build_path = Path(__file__).parent.parent / "build"
    build_path.mkdir(exist_ok=True)
    yield build_path


@pytest.fixture
def compiled_app(build_dir):
    """Compile a test executable with a dylib dependency.

    Creates:
    - libgreeting.dylib: A simple library with a greet() function
    - hello: An executable that links to libgreeting.dylib
    """
    # C source for the dynamic library
    lib_source = """\
#include <stdio.h>

void greet(const char *name) {
    printf("Hello, %s!\\n", name);
}
"""

    # C source for the executable
    exe_source = """\
extern void greet(const char *name);

int main(int argc, char *argv[]) {
    greet("World");
    return 0;
}
"""

    # Create source files
    lib_c = build_dir / "greeting.c"
    exe_c = build_dir / "hello.c"
    lib_c.write_text(lib_source)
    exe_c.write_text(exe_source)

    # Output paths
    dylib_path = build_dir / "libgreeting.dylib"
    exe_path = build_dir / "hello"

    # Compile the dylib with install_name set to its absolute path
    # (simulating a library installed in a non-system location)
    compile_lib = [
        "clang",
        "-dynamiclib",
        "-o",
        str(dylib_path),
        "-install_name",
        str(dylib_path),
        str(lib_c),
    ]
    result = subprocess.run(compile_lib, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(f"Failed to compile dylib: {result.stderr}")

    # Compile the executable, linking against the dylib
    compile_exe = [
        "clang",
        "-o",
        str(exe_path),
        "-L",
        str(build_dir),
        "-lgreeting",
        str(exe_c),
    ]
    result = subprocess.run(compile_exe, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(f"Failed to compile executable: {result.stderr}")

    # Verify the executable runs correctly before bundling
    env = os.environ.copy()
    env["DYLD_LIBRARY_PATH"] = str(build_dir)
    result = subprocess.run(
        [str(exe_path)], capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        pytest.fail(f"Executable failed to run: {result.stderr}")
    assert "Hello, World!" in result.stdout

    return exe_path, dylib_path


class TestIntegrationBundle:
    """Integration tests for Bundle class with real compiled binaries."""

    def test_bundle_with_dylib_dependency(self, build_dir, compiled_app):
        """Test bundling an executable with a dylib dependency."""
        exe_path, dylib_path = compiled_app

        # Create the bundle
        bundle = Bundle(
            target=exe_path,
            version="1.0",
            base_id="com.test",
            codesign=True,
        )
        bundle_path = bundle.create()

        # Verify bundle structure
        assert bundle_path.exists()
        assert bundle_path.name == "hello.app"
        assert (bundle_path / "Contents" / "MacOS" / "hello").exists()
        assert (bundle_path / "Contents" / "Info.plist").exists()
        assert (bundle_path / "Contents" / "PkgInfo").exists()

        # Verify the dylib was bundled
        libs_dir = bundle_path / "Contents" / "libs"
        assert libs_dir.exists(), "libs directory should exist"
        bundled_dylib = libs_dir / "libgreeting.dylib"
        assert bundled_dylib.exists(), "libgreeting.dylib should be bundled"

        # Verify the executable's dependency was updated
        exe_in_bundle = bundle_path / "Contents" / "MacOS" / "hello"
        otool_result = subprocess.run(
            ["otool", "-L", str(exe_in_bundle)],
            capture_output=True,
            text=True,
        )
        assert (
            "@executable_path/../libs/libgreeting.dylib" in otool_result.stdout
        ), "Executable should reference dylib via @executable_path"

        # Verify the bundled dylib's install name was updated
        otool_result = subprocess.run(
            ["otool", "-D", str(bundled_dylib)],
            capture_output=True,
            text=True,
        )
        assert (
            "@executable_path/../libs/libgreeting.dylib" in otool_result.stdout
        ), "Bundled dylib should have updated install name"

        # Run the bundled executable (should work without DYLD_LIBRARY_PATH)
        result = subprocess.run(
            [str(exe_in_bundle)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Bundled executable failed: {result.stderr}"
        )
        assert "Hello, World!" in result.stdout, (
            "Bundled executable should produce correct output"
        )


class TestIntegrationDylibBundler:
    """Integration tests for DylibBundler class with real compiled binaries."""

    def test_dylibbundler_standalone(self, build_dir, compiled_app):
        """Test using DylibBundler directly without Bundle wrapper."""
        exe_path, dylib_path = compiled_app

        # Create a standalone libs directory
        libs_dir = build_dir / "standalone_libs"
        if libs_dir.exists():
            import shutil

            shutil.rmtree(libs_dir)

        # Copy executable to a new location to avoid modifying the original
        standalone_exe = build_dir / "hello_standalone"
        import shutil

        shutil.copy2(exe_path, standalone_exe)

        # Use DylibBundler to bundle dependencies
        bundler = DylibBundler(
            dest_dir=libs_dir,
            overwrite_dir=True,
            create_dir=True,
            codesign=True,
            inside_lib_path="@executable_path/../standalone_libs/",
            files_to_fix=[standalone_exe],
        )

        bundler.collect_dependencies(standalone_exe)
        bundler.collect_sub_dependencies()
        bundler.process_collected_deps()

        # Verify the dylib was copied
        assert (libs_dir / "libgreeting.dylib").exists()

        # Verify the executable was updated
        otool_result = subprocess.run(
            ["otool", "-L", str(standalone_exe)],
            capture_output=True,
            text=True,
        )
        assert (
            "@executable_path/../standalone_libs/libgreeting.dylib"
            in otool_result.stdout
        )


class TestIntegrationChainedDependencies:
    """Integration tests with chained library dependencies (A -> B -> C)."""

    def test_chained_dylib_dependencies(self, build_dir):
        """Test bundling with chained dependencies: exe -> libA -> libB."""
        # C source for libB (no dependencies)
        lib_b_source = """\
#include <stdio.h>

void helper_func(void) {
    printf("Helper called\\n");
}
"""

        # C source for libA (depends on libB)
        lib_a_source = """\
extern void helper_func(void);

void main_func(void) {
    helper_func();
}
"""

        # C source for executable (depends on libA)
        exe_source = """\
extern void main_func(void);

int main(int argc, char *argv[]) {
    main_func();
    return 0;
}
"""

        # Write source files
        (build_dir / "lib_b.c").write_text(lib_b_source)
        (build_dir / "lib_a.c").write_text(lib_a_source)
        (build_dir / "chained.c").write_text(exe_source)

        lib_b_path = build_dir / "libhelper.dylib"
        lib_a_path = build_dir / "libmain.dylib"
        exe_path = build_dir / "chained"

        # Compile libB
        result = subprocess.run(
            [
                "clang",
                "-dynamiclib",
                "-o",
                str(lib_b_path),
                "-install_name",
                str(lib_b_path),
                str(build_dir / "lib_b.c"),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.fail(f"Failed to compile libB: {result.stderr}")

        # Compile libA (linking to libB)
        result = subprocess.run(
            [
                "clang",
                "-dynamiclib",
                "-o",
                str(lib_a_path),
                "-install_name",
                str(lib_a_path),
                "-L",
                str(build_dir),
                "-lhelper",
                str(build_dir / "lib_a.c"),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.fail(f"Failed to compile libA: {result.stderr}")

        # Compile executable (linking to libA)
        result = subprocess.run(
            [
                "clang",
                "-o",
                str(exe_path),
                "-L",
                str(build_dir),
                "-lmain",
                str(build_dir / "chained.c"),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.fail(f"Failed to compile executable: {result.stderr}")

        # Create the bundle
        bundle = Bundle(
            target=exe_path,
            version="1.0",
            base_id="com.test.chained",
        )
        bundle_path = bundle.create()

        # Verify both dylibs were bundled
        libs_dir = bundle_path / "Contents" / "libs"
        assert (libs_dir / "libmain.dylib").exists(), (
            "libmain.dylib should be bundled"
        )
        assert (libs_dir / "libhelper.dylib").exists(), (
            "libhelper.dylib should be bundled"
        )

        # Verify libA's dependency on libB was updated
        otool_result = subprocess.run(
            ["otool", "-L", str(libs_dir / "libmain.dylib")],
            capture_output=True,
            text=True,
        )
        assert (
            "@executable_path/../libs/libhelper.dylib" in otool_result.stdout
        ), "libmain.dylib should reference libhelper.dylib via @executable_path"

        # Run the bundled executable
        exe_in_bundle = bundle_path / "Contents" / "MacOS" / "chained"
        result = subprocess.run(
            [str(exe_in_bundle)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Bundled executable failed: {result.stderr}"
        )
        assert "Helper called" in result.stdout
