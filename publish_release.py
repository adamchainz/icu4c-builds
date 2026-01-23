#!/usr/bin/env uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "rich",
# ]
# ///
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rich import print as rprint

WORKFLOW_PATH = ".github/workflows/main.yml"
TIMEOUT_SECONDS = 1800


def run_gh_command(args: list[str]) -> str:
    """Run a gh command and return the output."""
    command = ["gh", *args]
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
    )
    if result.returncode != 0:
        rprint(
            f"[red]Error running gh command {' '.join(command)!r}[/red]",
            file=sys.stderr,
        )
        raise SystemExit(result.returncode)
    return result.stdout


def run_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    result = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
    )
    if result.returncode != 0:
        rprint(f"[red]Error running command: {' '.join(args)}[/red]", file=sys.stderr)
        rprint(f"[red]{result.stderr}[/red]", file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def resolve_commit_sha(ref: str) -> str:
    """Resolve @ or HEAD to the current commit SHA, otherwise return as-is."""
    if ref in ("@", "HEAD"):
        result = run_command(["git", "rev-parse", "HEAD"])
        return result.stdout.strip()
    return ref


def get_workflow_run(workflow_path: str, commit_sha: str) -> dict | None:
    """Get the workflow run for the given commit."""
    runs_json = run_gh_command(
        [
            "run",
            "list",
            "--commit",
            commit_sha,
            "--workflow",
            workflow_path,
            "--json",
            "databaseId,status,conclusion",
        ]
    )
    runs = json.loads(runs_json)

    if not runs:
        return None

    return runs[0]


def wait_for_completion(run_id: str, timeout: int = 1800) -> str:
    """Wait for the workflow run to complete. Returns the conclusion."""
    start_time = time.time()

    while True:
        if time.time() - start_time > timeout:
            raise TimeoutError(
                f"Workflow run did not complete within {timeout} seconds"
            )

        run_json = run_gh_command(
            ["run", "view", str(run_id), "--json", "status,conclusion"]
        )
        run = json.loads(run_json)

        status = run["status"]

        if status == "completed":
            return run["conclusion"]

        rprint(
            f"[dim]Waiting for workflow to complete... (status: {status})[/dim]",
            file=sys.stderr,
        )
        time.sleep(10)


def download_artifact(run_id: str, artifact_name: str, download_dir: Path) -> None:
    """Download a single artifact."""
    run_command(
        [
            "gh",
            "run",
            "download",
            str(run_id),
            "--name",
            artifact_name,
            "--dir",
            str(download_dir / artifact_name),
        ]
    )
    rprint(f"[dim]Downloaded {artifact_name}[/dim]", file=sys.stderr)


def get_artifact_names(run_id: str) -> list[str]:
    """Get list of artifact names from a workflow run."""
    artifacts_json = run_gh_command(
        ["api", f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/artifacts"]
    )
    data = json.loads(artifacts_json)
    return [artifact["name"] for artifact in data["artifacts"]]


def download_artifacts(run_id: str, download_dir: Path) -> None:
    """Download all artifacts from a workflow run in parallel."""
    artifact_names = get_artifact_names(run_id)
    rprint(
        f"[dim]Downloading {len(artifact_names)} artifact(s)...[/dim]", file=sys.stderr
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(download_artifact, run_id, name, download_dir)
            for name in artifact_names
        ]
        for future in futures:
            future.result()


def extract_artifacts(download_dir: Path) -> list[Path]:
    """Extract .tar.gz files from zip archives."""
    artifacts = []

    for artifact_dir in download_dir.iterdir():
        if not artifact_dir.is_dir():
            continue

        zip_files = list(artifact_dir.glob("*.zip"))

        if zip_files:
            for zip_file in zip_files:
                rprint(f"[dim]Extracting {zip_file.name}...[/dim]", file=sys.stderr)
                with zipfile.ZipFile(zip_file, "r") as zf:
                    zf.extractall(artifact_dir)

        tar_gz_files = list(artifact_dir.glob("*.tar.gz"))
        artifacts.extend(tar_gz_files)

    return artifacts


def create_release(version: str, commit_sha: str, artifacts: list[Path]) -> None:
    """Create a GitHub release with the given artifacts."""
    tag_name = f"v{version}"
    release_name = f"ICU4C {version}"

    rprint(f"[dim]Creating release {tag_name}...[/dim]", file=sys.stderr)

    cmd = [
        "gh",
        "release",
        "create",
        tag_name,
        "--title",
        release_name,
        "--target",
        commit_sha,
        "--notes",
        f"ICU4C version {version} builds for multiple platforms",
    ]

    for artifact in artifacts:
        cmd.append(str(artifact))

    run_command(cmd)

    rprint(f"[green]✓ Release {tag_name} created successfully[/green]")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish ICU4C release from GitHub Actions workflow artifacts"
    )
    parser.add_argument(
        "sha",
        help="Commit SHA to create release from",
    )
    parser.add_argument(
        "version",
        help="Version number for the release (e.g., '78.2')",
    )
    parser.add_argument(
        "--actually-publish",
        action="store_true",
        help="Actually create the release (default is dry-run)",
    )

    args = parser.parse_args(argv)

    commit_sha = resolve_commit_sha(args.sha)

    rprint(
        f"[dim]Looking up workflow run for commit {commit_sha}...[/dim]",
        file=sys.stderr,
    )

    run = get_workflow_run(WORKFLOW_PATH, commit_sha)
    if not run:
        rprint(
            f"[red]No workflow run found for commit {commit_sha} and workflow {WORKFLOW_PATH}[/red]",
            file=sys.stderr,
        )
        return 1

    run_id = run["databaseId"]
    status = run["status"]
    conclusion = run.get("conclusion")

    rprint(
        f"[dim]Found workflow run: {run_id} (status: {status})[/dim]",
        file=sys.stderr,
    )

    if status != "completed":
        rprint("[dim]Workflow is not complete, waiting...[/dim]", file=sys.stderr)
        conclusion = wait_for_completion(run_id, TIMEOUT_SECONDS)

    if conclusion != "success":
        rprint(
            f"[red]Workflow run did not succeed (conclusion: {conclusion})[/red]",
            file=sys.stderr,
        )
        return 1

    rprint("[green]✓ Workflow completed successfully[/green]", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        download_dir = tmppath / "downloads"
        download_dir.mkdir()

        download_artifacts(run_id, download_dir)

        artifacts = extract_artifacts(download_dir)

        if not artifacts:
            rprint(
                "[red]No .tar.gz artifacts found after extraction[/red]",
                file=sys.stderr,
            )
            return 1

        rprint("\n[bold]Artifacts to publish:[/bold]")
        for artifact in sorted(artifacts, key=lambda p: p.name):
            print(artifact.name)

        if args.actually_publish:
            create_release(args.version, commit_sha, artifacts)
            rprint(
                f"[green]✓ Successfully published release for version {args.version}[/green]"
            )
        else:
            rprint(
                "\n[yellow]Dry-run mode. Use --actually-publish to create the release.[/yellow]"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
