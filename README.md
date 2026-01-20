# ICU4C Builds

Pre-built [ICU4C (International Components for Unicode)](https://icu.unicode.org/) libraries for multiple platforms and architectures.

This repository builds ICU4C from source and publishes the compiled libraries as GitHub releases for easy consumption in other projects like [icu4py](https://github.com/adamchainz/icu4py).

## Releases

Releases are triggered by pushing a git tag (e.g., `78.1`). The tag name determines the ICU4C version to download and build. You can rebuild with tags like `78.1+build2` if needed.

## Available Builds

Each release provides ICU4C libraries for:

- **Linux (glibc)**: x86_64, i686, aarch64
- **Linux (musl)**: x86_64, i686, aarch64
- **macOS**: arm64, x86_64
- **Windows**: AMD64, x86, ARM64

## Build Configuration

ICU4C is built with the following settings:

- **Data packaging**: archive (`.dat` file)
- **Shared libraries**: enabled
- **Static libraries**: disabled
- **Tests/samples**: disabled
- **Symbol renaming**: disabled
- **Charset**: UTF-8 hardcoded

## Usage

Download the pre-built libraries for your platform from the [releases page](../../releases).

Example for Linux x86_64:

```bash
curl -L -o icu.tar.gz https://github.com/adamchainz/icu4c-builds/releases/download/78.1/icu-78.1-linux-x86_64.tar.gz
tar xzf icu.tar.gz
export ICU_ROOT=$PWD/icu-78.1-linux-x86_64
export CPPFLAGS="-I$ICU_ROOT/include"
export LDFLAGS="-L$ICU_ROOT/lib"
```

## Building Locally

To build ICU4C locally:

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run the build (Docker required for Linux builds)
uv run build.py --platform linux --arch x86_64
# or
uv run build.py --platform macos --arch arm64
# or
uv run build.py --platform windows --arch AMD64
```

The ICU4C version is defined in the `ICU_VERSION` constant at the top of `build.py`.
