#!/usr/bin/env python3
"""Build ICU from source for the current platform."""

from __future__ import annotations

import argparse
import ctypes
import platform
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ICU_VERSION = "78.2"


def run(cmd: list[str], **kwargs) -> None:
    """Run a subprocess command."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def get_docker_image(platform_name: str, arch: str) -> str:
    """Get the Docker image to use for Linux builds."""
    try:
        from cibuildwheel.options import _get_pinned_container_images

        config = _get_pinned_container_images()
        if platform_name == "linux":
            return config[arch]["manylinux_2_28"]
        else:  # linux-musl
            return config[arch]["musllinux_1_2"]
    except Exception as e:
        print(f"Warning: Could not get pinned image from cibuildwheel: {e}")
        if platform_name == "linux":
            return f"quay.io/pypa/manylinux_2_28_{arch}"
        else:
            return f"quay.io/pypa/musllinux_1_2_{arch}"


def docker_platform(arch: str) -> str:
    """Convert architecture to Docker platform."""
    arch_mapping = {
        "x86_64": "linux/amd64",
        "i686": "linux/386",
        "aarch64": "linux/arm64",
    }
    return arch_mapping.get(arch, f"linux/{arch}")


def build_in_docker(platform_name: str, arch: str) -> None:
    """Build ICU inside a Docker container."""
    image = get_docker_image(platform_name, arch)
    docker_plat = docker_platform(arch)

    work_dir = Path.cwd()

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{work_dir}:/work",
        "-w",
        "/work",
        "--platform",
        docker_plat,
        image,
        "python3",
        "build.py",
        "--platform",
        platform_name,
        "--arch",
        arch,
        "--in-docker",
    ]

    run(cmd)


def download_icu(version: str, dest_dir: Path) -> Path:
    """Download ICU source tarball."""
    url = f"https://github.com/unicode-org/icu/releases/download/release-{version}/icu4c-{version}-sources.tgz"

    tarball_path = dest_dir / f"icu4c-{version}.tgz"

    print(f"Downloading ICU {version} from {url}")
    with urllib.request.urlopen(url) as response, open(tarball_path, "wb") as f:
        f.write(response.read())

    print(f"Extracting {tarball_path}")
    with tarfile.open(tarball_path, "r:gz") as tar:
        tar.extractall(dest_dir)

    return dest_dir / "icu" / "source"


def build_unix(source_dir: Path, install_dir: Path, platform_name: str) -> None:
    """Build ICU on Unix-like systems (Linux, macOS)."""
    run(["chmod", "+x", "configure", "runConfigureICU", "install-sh"], cwd=source_dir)

    if platform_name == "linux-musl":
        icu_platform = "Linux"
    elif platform_name == "linux":
        icu_platform = "Linux/gcc"
    elif platform_name == "macos":
        icu_platform = "macOS"
    else:
        raise ValueError(f"Unexpected platform_name: {platform_name}")

    configure_args = [
        "./runConfigureICU",
        icu_platform,
        f"--prefix={install_dir.absolute()}",
        "--with-data-packaging=archive",
        "--disable-samples",
        "--disable-tests",
        "--disable-renaming",
        "CPPFLAGS=-DU_CHARSET_IS_UTF8=1",
    ]

    run(configure_args, cwd=source_dir)

    data_out_dir = source_dir / "data" / "out" / "tmp"
    data_out_dir.mkdir(parents=True, exist_ok=True)

    nproc = subprocess.run(
        ["nproc"] if platform.system() == "Linux" else ["sysctl", "-n", "hw.ncpu"],
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()

    run(["make", f"-j{nproc}"], cwd=source_dir)
    run(["make", "install"], cwd=source_dir)


def build_windows(source_dir: Path, install_dir: Path, arch: str) -> None:
    """Build ICU on Windows using MSBuild."""
    if arch == "AMD64":
        platform = "x64"
    elif arch == "ARM64":
        platform = "ARM64"
    else:
        platform = "Win32"

    solution_file = source_dir / "allinone" / "allinone.sln"

    run(
        [
            "msbuild",
            str(solution_file),
            "/p:Configuration=Release",
            f"/p:Platform={platform}",
            "/m",
        ]
    )

    install_dir.mkdir(parents=True, exist_ok=True)

    if platform == "Win32":
        bin_dir = source_dir / ".." / "bin"
        lib_dir = source_dir / ".." / "lib"
    elif platform == "x64":
        bin_dir = source_dir / ".." / "bin64"
        lib_dir = source_dir / ".." / "lib64"
    else:
        bin_dir = source_dir / ".." / "binARM64"
        lib_dir = source_dir / ".." / "libARM64"

    if bin_dir.exists():
        shutil.copytree(bin_dir, install_dir / "bin", dirs_exist_ok=True)
    if lib_dir.exists():
        shutil.copytree(lib_dir, install_dir / "lib", dirs_exist_ok=True)

    include_src = source_dir / "common" / "unicode"
    include_dest = install_dir / "include" / "unicode"
    include_dest.mkdir(parents=True, exist_ok=True)
    if include_src.exists():
        shutil.copytree(include_src, include_dest, dirs_exist_ok=True)

    data_dir = source_dir / ".." / "data"
    if data_dir.exists():
        shutil.copytree(
            data_dir, install_dir / "share" / "icu" / ICU_VERSION, dirs_exist_ok=True
        )


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
    parser = argparse.ArgumentParser(description="Build ICU4C from source")
    parser.add_argument(
        "--platform",
        required=True,
        help="Platform name (linux, linux-musl, macos, windows)",
    )
    parser.add_argument(
        "--arch", required=True, help="Architecture (x86_64, aarch64, etc.)"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("dist"), help="Output directory"
    )
    parser.add_argument(
        "--in-docker", action="store_true", help="Running inside Docker (internal flag)"
    )
    args = parser.parse_args()

    if args.platform in ("linux", "linux-musl") and not args.in_docker:
        build_in_docker(args.platform, args.arch)
        return

    work_dir = Path("build")
    work_dir.mkdir(exist_ok=True)

    install_dir = work_dir / "install"

    source_dir = download_icu(ICU_VERSION, work_dir)

    if args.platform in ("linux", "linux-musl", "macos"):
        build_unix(source_dir, install_dir, args.platform)
    elif args.platform == "windows":
        build_windows(source_dir, install_dir, args.arch)
    else:
        print(f"Unknown platform: {args.platform}")
        raise SystemExit(1)

    test_icu(install_dir, ICU_VERSION)

    args.output_dir.mkdir(exist_ok=True)
    package_build(install_dir, args.output_dir, ICU_VERSION, args.platform, args.arch)

    print("\n✓ Build complete!")


if __name__ == "__main__":
    main()
