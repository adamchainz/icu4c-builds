# ICU4C Builds

Pre-built [ICU (International Components for Unicode)](https://icu.unicode.org/) libraries for multiple platforms and architectures.

This repository builds ICU from source and publishes the compiled libraries as GitHub releases for easy consumption in other projects like [icu4py](https://github.com/adamchainz/icu4py).

## Available Builds

Each release provides ICU libraries for:

- **Linux (glibc)**: x86_64, i686, aarch64
- **Linux (musl)**: x86_64, i686, aarch64
- **macOS**: arm64, x86_64
- **Windows**: AMD64, x86

## Build Configuration

ICU is built with the following settings:

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
