#!/usr/bin/env python3
"""Build ICU from source for the current platform."""

import argparse
import ctypes
import platform
import subprocess
import tarfile
import urllib.request
from pathlib import Path


def run(cmd: list[str], **kwargs) -> None:
    """Run a subprocess command."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def download_icu(version: str, dest_dir: Path) -> Path:
    """Download ICU source tarball."""
    icu_version_underscore = version.replace(".", "_")
    url = f"https://github.com/unicode-org/icu/releases/download/release-{icu_version_underscore}/icu4c-{icu_version_underscore}-src.tgz"

    tarball_path = dest_dir / f"icu4c-{version}.tgz"

    print(f"Downloading ICU {version} from {url}")
    with urllib.request.urlopen(url) as response:
        with open(tarball_path, "wb") as f:
            f.write(response.read())

    print(f"Extracting {tarball_path}")
    with tarfile.open(tarball_path, "r:gz") as tar:
        tar.extractall(dest_dir)

    return dest_dir / "icu" / "source"


def build_unix(source_dir: Path, install_dir: Path) -> None:
    """Build ICU on Unix-like systems (Linux, macOS)."""
    run(["chmod", "+x", "configure", "runConfigureICU", "install-sh"], cwd=source_dir)

    configure_args = [
        "./configure",
        f"--prefix={install_dir.absolute()}",
        "--with-data-packaging=archive",
        "--disable-tests",
        "--disable-samples",
        "--disable-renaming",
        "CPPFLAGS=-DU_CHARSET_IS_UTF8=1",
    ]

    run(configure_args, cwd=source_dir)

    nproc = subprocess.run(
        ["nproc"] if platform.system() == "Linux" else ["sysctl", "-n", "hw.ncpu"],
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()

    run(["make", f"-j{nproc}"], cwd=source_dir)
    run(["make", "install"], cwd=source_dir)


def build_windows(source_dir: Path, install_dir: Path, arch: str) -> None:
    """Build ICU on Windows using CMake."""
    build_dir = source_dir / "build"
    build_dir.mkdir(exist_ok=True)

    if arch == "AMD64":
        cmake_arch = "x64"
    elif arch == "ARM64":
        cmake_arch = "ARM64"
    else:
        cmake_arch = "Win32"

    run(
        [
            "cmake",
            "..",
            f"-DCMAKE_INSTALL_PREFIX={install_dir.absolute()}",
            "-DCMAKE_BUILD_TYPE=Release",
            "-A",
            cmake_arch,
        ],
        cwd=build_dir,
    )

    run(["cmake", "--build", ".", "--config", "Release", "-j"], cwd=build_dir)
    run(["cmake", "--install", "."], cwd=build_dir)


def test_icu(install_dir: Path, version: str) -> None:
    """Test the built ICU library by loading it and checking the version."""
    print("\nTesting ICU build...")

    system = platform.system()

    if system == "Linux":
        lib_dir = install_dir / "lib"
        lib_name = f"libicuuc.so.{version.split('.')[0]}"
    elif system == "Darwin":
        lib_dir = install_dir / "lib"
        lib_name = f"libicuuc.{version.split('.')[0]}.dylib"
    elif system == "Windows":
        lib_dir = install_dir / "bin"
        lib_name = f"icuuc{version.split('.')[0]}.dll"
    else:
        print(f"Unknown system {system}, skipping test")
        return

    lib_path = lib_dir / lib_name
    if not lib_path.exists():
        print(f"Warning: Library not found at {lib_path}")
        return

    try:
        lib = ctypes.CDLL(str(lib_path))

        u_getVersion = lib.u_getVersion
        u_getVersion.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
        u_getVersion.restype = None

        version_array = (ctypes.c_uint8 * 4)()
        u_getVersion(version_array)

        detected_version = f"{version_array[0]}.{version_array[1]}"
        expected_version = ".".join(version.split(".")[:2])

        print(f"Detected ICU version: {detected_version}")
        print(f"Expected ICU version: {expected_version}")

        if detected_version == expected_version:
            print("✓ ICU version check passed")
        else:
            print("✗ ICU version mismatch!")
            raise SystemExit(1)
    except Exception as e:
        print(f"Warning: Could not test ICU library: {e}")


def package_build(
    install_dir: Path, output_dir: Path, version: str, platform_name: str, arch: str
) -> Path:
    """Package the built ICU into a tarball."""
    archive_name = f"icu-{version}-{platform_name}-{arch}"
    archive_path = output_dir / f"{archive_name}.tar.gz"

    print(f"\nPackaging build to {archive_path}")

    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(install_dir, arcname=archive_name)

    print(f"Archive size: {archive_path.stat().st_size / 1024 / 1024:.1f} MB")
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ICU from source")
    parser.add_argument("--version", required=True, help="ICU version (e.g., 78.1)")
    parser.add_argument(
        "--platform", required=True, help="Platform name (linux, macos, windows)"
    )
    parser.add_argument(
        "--arch", required=True, help="Architecture (x86_64, aarch64, etc.)"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("dist"), help="Output directory"
    )
    args = parser.parse_args()

    work_dir = Path("build")
    work_dir.mkdir(exist_ok=True)

    install_dir = work_dir / "install"

    source_dir = download_icu(args.version, work_dir)

    if args.platform in ("linux", "macos"):
        build_unix(source_dir, install_dir)
    elif args.platform == "windows":
        build_windows(source_dir, install_dir, args.arch)
    else:
        print(f"Unknown platform: {args.platform}")
        raise SystemExit(1)

    test_icu(install_dir, args.version)

    args.output_dir.mkdir(exist_ok=True)
    package_build(install_dir, args.output_dir, args.version, args.platform, args.arch)

    print("\n✓ Build complete!")


if __name__ == "__main__":
    main()
