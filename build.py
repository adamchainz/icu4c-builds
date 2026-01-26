#!/usr/bin/env python3
"""Build ICU from source for the current platform."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from textwrap import dedent
from typing import assert_never

ICU_VERSION = "78.2"


def run(cmd: list[str], **kwargs) -> None:
    """Run a subprocess command."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def detect_arch() -> str:
    """Detect the current architecture."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        machine_upper = platform.machine().upper()
        if machine_upper in ("AMD64", "X86_64"):
            return "AMD64"
        elif machine_upper == "ARM64":
            return "ARM64"
        else:
            return machine_upper

    if machine in ("x86_64", "amd64"):
        return "x86_64"
    elif machine in ("aarch64", "arm64"):
        return "aarch64"
    else:
        return machine


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


def build_in_docker(platform_name: str, arch: str) -> None:
    """Build ICU inside a Docker container."""
    image = get_docker_image(platform_name, arch)

    work_dir = Path.cwd()

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{work_dir}:/work",
        "-w",
        "/work",
        image,
        "python3",
        "build.py",
        "--platform",
        platform_name,
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


def build_unix(
    source_dir: Path, install_dir: Path, platform_name: str, arch: str
) -> None:
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
        "--with-data-packaging=library",
        "--disable-samples",
        "--disable-tests",
    ]

    env = os.environ.copy()
    env["CPPFLAGS"] = "-DU_CHARSET_IS_UTF8=1"
    if platform_name == "macos":
        env["LDFLAGS"] = "-Wl,-headerpad_max_install_names"

    run(configure_args, cwd=source_dir, env=env)

    data_out_dir = source_dir / "data" / "out" / "tmp"
    data_out_dir.mkdir(parents=True, exist_ok=True)

    nproc = os.cpu_count() or 1
    run(["make", "-s", f"-j{nproc}"], cwd=source_dir, env=env)
    run(["make", "-s", "install"], cwd=source_dir, env=env)


def build_windows(source_dir: Path, install_dir: Path, arch: str) -> None:
    """Build ICU on Windows using MSBuild."""
    if arch == "AMD64":
        msbuild_platform = "x64"
    elif arch == "ARM64":
        msbuild_platform = "ARM64"
    else:
        raise ValueError(f"Unsupported Windows architecture: {arch}")

    solution_file = source_dir / "allinone" / "allinone.sln"

    run(
        [
            "msbuild",
            str(solution_file),
            "/p:Configuration=Release",
            f"/p:Platform={msbuild_platform}",
            "/m",
            "/v:minimal",
        ]
    )

    install_dir.mkdir(parents=True, exist_ok=True)

    if msbuild_platform == "x64":
        bin_dir = source_dir / ".." / "bin64"
        lib_dir = source_dir / ".." / "lib64"
    elif msbuild_platform == "ARM64":
        bin_dir = source_dir / ".." / "binARM64"
        lib_dir = source_dir / ".." / "libARM64"
    else:
        assert_never(msbuild_platform)

    shutil.copytree(bin_dir, install_dir / "bin", dirs_exist_ok=True)
    shutil.copytree(lib_dir, install_dir / "lib", dirs_exist_ok=True)
    shutil.copytree(
        source_dir / ".." / "include", install_dir / "include", dirs_exist_ok=True
    )


def test_icu(install_dir: Path, version: str, arch: str) -> None:
    """Test the built ICU library by compiling and running a small C++ program."""
    print("\nTesting ICU build...")

    system = platform.system()

    test_cpp = dedent("""
        #include <unicode/uversion.h>
        #include <unicode/utypes.h>
        #include <unicode/unistr.h>
        #include <unicode/msgfmt.h>
        #include <unicode/locid.h>
        #include <iostream>

        int main() {
            // Version check
            UVersionInfo versionArray;
            u_getVersion(versionArray);
            std::cout << (int)versionArray[0] << "." << (int)versionArray[1] << "\\n";

            // MessageFormat test
            UErrorCode status = U_ZERO_ERROR;

            icu::Locale locale("en", "US");
            icu::UnicodeString pattern(u"Hello {name}", -1);

            icu::MessageFormat msgFmt(pattern, locale, status);
            if (U_FAILURE(status)) {
                std::cerr << "MessageFormat ctor failed: " << status << std::endl;
                return 1;
            }

            icu::Formattable args[1];
            const icu::UnicodeString argNames[] = { icu::UnicodeString(u"name", -1) };

            args[0].setString(icu::UnicodeString(u"World", -1));

            icu::UnicodeString result;
            msgFmt.format(argNames, args, 1, result, status);
            if (U_FAILURE(status)) {
                std::cerr << "MessageFormat::format failed: " << status << std::endl;
                return 1;
            }

            std::string utf8;
            result.toUTF8String(utf8);
            std::cout << utf8 << "\\n";

            return 0;
        }
    """)

    test_dir = Path("build") / "test"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_cpp_path = test_dir / "test_icu.cpp"
    test_cpp_path.write_text(test_cpp)

    include_dir = install_dir / "include"
    lib_dir = install_dir / ("lib" if system != "Windows" else "bin")

    if system == "Windows":
        exe_path = test_dir / "test_icu.exe"
        lib_core = install_dir / "lib" / "icuuc.lib"
        lib_i18n = install_dir / "lib" / "icuin.lib"
        lib_data = install_dir / "lib" / "icudt.lib"

        if arch == "AMD64":
            msbuild_platform = "x64"
        elif arch == "ARM64":
            msbuild_platform = "ARM64"
        else:
            raise ValueError(f"Unsupported Windows architecture: {arch}")

        vcxproj = dedent(f"""<?xml version="1.0" encoding="utf-8"?>
            <Project DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
              <ItemGroup Label="ProjectConfigurations">
                <ProjectConfiguration Include="Release|{msbuild_platform}">
                  <Configuration>Release</Configuration>
                  <Platform>{msbuild_platform}</Platform>
                </ProjectConfiguration>
              </ItemGroup>
              <PropertyGroup Label="Globals">
                <ProjectGuid>{{12345678-1234-1234-1234-123456789012}}</ProjectGuid>
              </PropertyGroup>
              <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />
              <PropertyGroup Label="Configuration">
                <ConfigurationType>Application</ConfigurationType>
                <PlatformToolset>v143</PlatformToolset>
                <CharacterSet>Unicode</CharacterSet>
              </PropertyGroup>
              <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />
              <PropertyGroup>
                <OutDir>{test_dir.absolute()}\\</OutDir>
                <IntDir>{test_dir.absolute()}\\obj\\</IntDir>
                <TargetName>test_icu</TargetName>
              </PropertyGroup>
              <ItemDefinitionGroup>
                <ClCompile>
                  <LanguageStandard>stdcpplatest</LanguageStandard>
                  <AdditionalIncludeDirectories>{include_dir.absolute()}</AdditionalIncludeDirectories>
                </ClCompile>
                <Link>
                  <AdditionalDependencies>{lib_core.absolute()};{lib_i18n.absolute()};{lib_data.absolute()};%(AdditionalDependencies)</AdditionalDependencies>
                </Link>
              </ItemDefinitionGroup>
              <ItemGroup>
                <ClCompile Include="{test_cpp_path.absolute()}" />
              </ItemGroup>
              <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
            </Project>
        """)

        vcxproj_path = test_dir / "test_icu.vcxproj"
        vcxproj_path.write_text(vcxproj)

        compile_cmd = [
            "msbuild",
            str(vcxproj_path),
            "/p:Configuration=Release",
            f"/p:Platform={msbuild_platform}",
            "/nologo",
            "/v:minimal",
        ]
    else:
        exe_path = test_dir / "test_icu"
        compiler = "g++" if system == "Linux" else "clang++"

        compile_cmd = [
            compiler,
            str(test_cpp_path),
            f"-I{include_dir.absolute()}",
            f"-L{lib_dir.absolute()}",
            "-licui18n",
            "-licuuc",
            "-licudata",
            "-std=c++17",
            "-o",
            str(exe_path),
        ]

    run(compile_cmd)

    env = os.environ.copy()
    if system == "Linux":
        env["LD_LIBRARY_PATH"] = str(lib_dir.absolute())
    elif system == "Darwin":
        env["DYLD_LIBRARY_PATH"] = str(lib_dir.absolute())
    elif system == "Windows":
        dll_dir = install_dir / "bin"
        env["PATH"] = f"{dll_dir.absolute()};{env.get('PATH', '')}"

    result = subprocess.run(
        [str(exe_path.absolute())],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
        cwd=test_dir,
    )
    if result.returncode != 0:
        raise SystemExit(1)

    output_lines = [line for line in result.stdout.strip().splitlines() if line]
    if len(output_lines) < 2:
        print("Unexpected C++ ICU test output")
        raise SystemExit(1)

    detected_version = output_lines[0].strip()
    expected_version = ".".join(version.split(".")[:2])
    print(f"Detected ICU version (C++ test): {detected_version}")
    print(f"Expected ICU version: {expected_version}")
    if detected_version != expected_version:
        print("ICU version mismatch in C++ test!")
        raise SystemExit(1)

    formatted = output_lines[1].strip()
    print(f"MessageFormat output: {formatted!r}")
    if formatted != "Hello World":
        print("Unexpected MessageFormat output")
        raise SystemExit(1)

    print("ICU C++ MessageFormat test passed")


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
        "--output-dir", type=Path, default=Path("dist"), help="Output directory"
    )
    parser.add_argument(
        "--in-docker", action="store_true", help="Running inside Docker (internal flag)"
    )
    args = parser.parse_args()

    arch = detect_arch()
    print(f"Detected architecture: {arch}")

    if args.platform in ("linux", "linux-musl") and not args.in_docker:
        build_in_docker(args.platform, arch)
        return

    work_dir = Path("build")
    work_dir.mkdir(exist_ok=True)

    install_dir = work_dir / "install"

    source_dir = download_icu(ICU_VERSION, work_dir)

    if args.platform in ("linux", "linux-musl", "macos"):
        build_unix(source_dir, install_dir, args.platform, arch)
    elif args.platform == "windows":
        build_windows(source_dir, install_dir, arch)
    else:
        print(f"Unknown platform: {args.platform}")
        raise SystemExit(1)

    test_icu(install_dir, ICU_VERSION, arch)

    args.output_dir.mkdir(exist_ok=True)
    package_build(install_dir, args.output_dir, ICU_VERSION, args.platform, arch)

    print("\nBuild complete!")


if __name__ == "__main__":
    main()
