#!/usr/bin/env python3

"""
tree-sitter-dl.py by Diego Frias

This is a simple Python script to help replace the archived nvim-treesitter.
It should work with recent versions of Python 3. To run it, you must have the
following programs on your computer:

- git
- tree-sitter (see https://tree-sitter.github.io/tree-sitter/creating-parsers/1-getting-started.html)

Using this script is simple. To install:

./tree-sitter-dl.py install python zig rust

To uninstall:

./tree-sitter-dl.py uninstall python zig rust

If you would like to install specific parsers:

./tree-sitter-dl.py install python:https://github.com/tree-sitter/tree-sitter-python@v0.25.0

Use the --help flag for all options. Note that, if a runtime directory is not
provided, tree-sitter-dl.py falls back to your default Neovim config directory.
For example, on macOS, this is ~/.config/nvim.

Read the corresponding blog post for more information:
https://dzfrias.dev/blog/tree-sitter-post-archival

Feel free to modify this script as you wish.
"""

import argparse
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen


LOCKFILE_NAME = "tree-sitter-dl-lock.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tree-sitter-dl",
        description="Download tree-sitter parsers for Neovim",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    parser_install = subparsers.add_parser(
        "install", help="install or update tree-sitter parsers"
    )
    parser_uninstall = subparsers.add_parser(
        "uninstall", help="uninstall tree-sitter parsers"
    )
    parser_list = subparsers.add_parser(
        "list", help="list installed tree-sitter parsers"
    )

    # `install` subcommand
    parser_install.add_argument("parsers", help="parsers to install/update", nargs="+")
    parser_install.add_argument(
        "-o", "--output", type=Path, help="output directory", default=None
    )
    parser_install.add_argument(
        "-w",
        "--wasm",
        help="install wasm parsers instead of shared objects",
        action="store_true",
    )
    parser_install.add_argument(
        "-y",
        "--no-confirm",
        help="skip warnings and user input",
        action="store_true",
    )

    # `uninstall` subcommand
    parser_uninstall.add_argument("parsers", help="parsers to uninstall", nargs="+")
    parser_uninstall.add_argument(
        "-d",
        "--dir",
        type=Path,
        help="directory where runtime files live",
        default=None,
    )

    # `list` subcommand
    parser_list.add_argument(
        "-d",
        "--dir",
        type=Path,
        help="directory where runtime files live",
        default=None,
    )
    parser_list.add_argument(
        "-v",
        "--verbose",
        help="include more information in the parser list",
        action="store_true",
    )

    args = parser.parse_args()
    if args.command == "install":
        output_dir = get_config_home() if args.output is None else args.output
        print(f"Output directory: {output_dir}")
        parsers = []
        revisions = {}
        for parser in args.parsers:
            if ":" not in parser:
                if parser in parsers:
                    print(f"Duplicate parser {parser} found")
                    return
                parsers.append(parser)
                continue
            name, repo_maybe_rev = parser.split(":", 1)
            if name in parsers:
                print(f"Duplicate parser {name} found")
                return
            parsers.append(name)
            split = repo_maybe_rev.split("@")
            if len(split) > 2:
                print(f"Error parsing parser {parser}")
                return
            repo = split[0]
            rev = split[1] if len(split) == 2 else None
            revisions[name] = (repo, rev)
        install_or_update(
            parsers, revisions, output_dir, args.wasm, not args.no_confirm
        )
    elif args.command == "uninstall":
        rt_dir = get_config_home() if args.dir is None else args.dir
        print(f"Runtime directory: {rt_dir}")
        uninstall(args.parsers, rt_dir)
    elif args.command == "list":
        rt_dir = get_config_home() if args.dir is None else args.dir
        list_parsers(rt_dir, args.verbose)
    else:
        assert False


def install_or_update(
    parsers: list[str],
    revisions: dict[str, tuple[str, str | None]],
    output_dir: Path,
    wasm: bool,
    confirm: bool,
) -> None:
    LIST_OF_PARSERS_URL = (
        "https://github.com/tree-sitter/tree-sitter/wiki/List-of-parsers"
    )
    print(f"Reading tree-sitter parser list at {LIST_OF_PARSERS_URL}")
    with urlopen(LIST_OF_PARSERS_URL) as response:
        data = response.read()
        text = data.decode("UTF-8")
    parser = PageParser()
    parser.feed(text)
    repos = parser.repos

    with tempfile.TemporaryDirectory() as tempdir:
        # We will use these directories as our program output
        download_path = Path(tempdir)
        print(f"Using temporary download path {download_path}")
        queries_dir = output_dir / "queries"
        queries_dir.mkdir(exist_ok=True)
        print(f"Using queries directory {queries_dir}")
        parser_dir = output_dir / "parser"
        parser_dir.mkdir(exist_ok=True)
        print(f"Using parser directory {queries_dir}")

        # Download nvim_treesitter (which we will use for getting runtime queries)
        print("Downloading nvim-treesitter (archived)")
        nvim_treesitter = download_repo(
            "https://github.com/nvim-treesitter/nvim-treesitter", "main", download_path
        )
        print(f"Using nvim-treesitter at {nvim_treesitter}")

        lockfile_path = output_dir / LOCKFILE_NAME
        lockdata = read_or_create_lockfile(lockfile_path)
        print(f"Using lockfile at {lockfile_path}")

        # All candidates for parser repositories. Note that some repositories might
        # be for the same parser, so we will try to choose the best one.
        candidates = [
            repo
            for repo in repos
            if repo.name in parsers and repo.name not in revisions
        ]
        print("Selecting best installation repositories")
        best_repos = select_best_install_repos(candidates, lockdata, wasm, confirm)
        for name, revision_info in revisions.items():
            # Use the specified repository for the download
            best_repos.append(
                ParserRepo(
                    name,
                    url=revision_info[0],
                    last_modified=date.today(),
                )
            )
        print(f"Installing parsers: {', '.join(r.name for r in best_repos)}")

        # Parallelize downloading
        with ThreadPoolExecutor(max_workers=8) as pool:
            for result in pool.map(
                lambda repo: install_or_update_repo(
                    repo,
                    wasm,
                    revisions.get(repo.name, ("", None))[1],
                    lockdata,
                    nvim_treesitter,
                    download_path,
                    queries_dir,
                    parser_dir,
                ),
                best_repos,
            ):
                pass

        print(f"Writing lockfile {lockfile_path}")
        write_lockfile(lockfile_path, lockdata)
        print("Installation complete!")


def install_or_update_repo(
    repo: ParserRepo,
    wasm: bool,
    revision: str | None,
    lockdata: Lockdata,
    nvim_treesitter: Path,
    download_path: Path,
    queries_dir: Path,
    parser_dir: Path,
):
    print(f"Starting install for {repo.name}")
    if revision is None:
        print(f"No revision provided, getting last commit for {repo.name}")
        resolved_revision = get_last_revision(repo.url)
    else:
        print(f"Resolving revision {revision} for {repo.name}")
        resolved_revision = resolve_revision(repo.url, revision)
    print(f"Using revision {resolved_revision} for {repo.name}")
    # Check if our revisions match, otherwise pull the updates
    if (
        repo.name in lockdata.repos
        and resolved_revision == lockdata.repos[repo.name].rev
        and repo.url == lockdata.repos[repo.name].src
    ):
        print(f"{repo.name} already up-to-date!")
        return
    print(f"Updates found for {repo.name}")
    if repo.name in lockdata.repos and lockdata.repos[repo.name].wasm:
        wasm = True
    so_suffix = "wasm" if wasm else get_shared_lib_suffix()
    print(f"Using shared library suffix .{so_suffix}")
    print(f"Downloading {repo.url} repository ({resolved_revision})")
    dir = download_repo(repo.url, resolved_revision, download_path)
    print(f"Using {dir} (downloaded) for {repo.url}")
    cmd = [
        "tree-sitter",
        "build",
        "--output",
        str(parser_dir / f"{repo.name}.{so_suffix}"),
    ]
    if wasm:
        cmd.append("--wasm")
    print(f"Running: {' '.join(map(str, cmd))}")
    # Get shared library
    subprocess.run(cmd, cwd=dir)
    # Get queries
    print(f"Getting runtime queries for {repo.url}")
    copy_queries(nvim_treesitter / "runtime" / "queries", repo.name, queries_dir)
    # Update lockfile
    lockdata.repos[repo.name] = RepoLockdata(
        rev=resolved_revision, src=repo.url, wasm=wasm
    )


def copy_queries(copy_base: Path, name: str, queries_dir: Path) -> None:
    queries = copy_base / name
    print(f"Copying {queries} into {queries_dir}")
    copy_into_clobber(queries, queries_dir)
    for query_file in queries.iterdir():
        if query_file.is_dir():
            continue
        inherits: list[str] = []
        with query_file.open("r") as f:
            line = f.readline()
            if not line.startswith("; inherits"):
                continue
            inherits = line.split(":")[1].strip().split(",")
        print(
            f"Found inherited queries in {query_file} for {name}: {', '.join(inherits)}"
        )
        for parent in inherits:
            copy_queries(copy_base, parent, queries_dir)


def select_best_install_repos(
    repos: list[ParserRepo], lockdata: Lockdata, wasm: bool, confirm: bool
) -> list[ParserRepo]:
    repo_map: defaultdict[str, list[ParserRepo]] = defaultdict(list)
    for repo in repos:
        repo_map[repo.name].append(repo)
    best: list[ParserRepo] = []
    for candidates in repo_map.values():
        found = False
        for candidate in candidates:
            # Already in lockdata (trusted source)
            if (
                candidate.name in lockdata.repos
                and candidate.url == lockdata.repos[candidate.name].src
            ):
                best.append(candidate)
                found = True
                break
        if found:
            continue
        for candidate in candidates:
            owner = candidate.url.split("/")[-2]
            # Trusted repositories with well-known parsers
            if owner == "tree-sitter-grammars" or owner == "tree-sitter":
                print(f"Selected {candidate.url} for parser {candidate.name}")
                best.append(candidate)
                found = True
                break
        if found:
            continue
        # Sort by last updated to find the best parser
        last_updated = sorted(candidates, key=lambda r: r.last_modified, reverse=True)
        # We print a warning and ask the user to confirm. If they are using Wasm, we don't ask for
        # this confirmation because WASI is sandboxed by default.
        if confirm and not wasm:
            print(
                f"\nWARNING: found potentially untrusted parser repository {last_updated[0].url}"
            )
            print(
                "Make sure you trust this parser before letting it run on your machine"
            )
            print(
                "Alternatively, use Wasm parsers and build Neovim with ENABLE_WASMTIME"
            )
            user_input = input("Type 'yes' if you would like to proceed: ")
            if user_input.lower() != "yes":
                print(f"Skipping {last_updated[0].name}")
                continue
        print(f"Selected {last_updated[0].url} for parser {last_updated[0].name}")
        best.append(last_updated[0])
    return best


def uninstall(parsers: list[str], rt_dir: Path) -> None:
    lockfile_path = rt_dir / LOCKFILE_NAME
    lockdata = read_or_create_lockfile(lockfile_path)
    print(f"Using lockfile at {lockfile_path}")
    queries_dir = rt_dir / "queries"
    print(f"Using queries directory {queries_dir} (may not exist)")
    parser_dir = rt_dir / "parser"
    print(f"Using parser directory {queries_dir} (may not exist)")

    for name in parsers:
        print(f"Uninstalling {name}")
        queries = queries_dir / name
        if name in lockdata.repos and lockdata.repos[name].wasm:
            so_suffix = "wasm"
        else:
            so_suffix = get_shared_lib_suffix()
        print(f"Using shared library suffix .{so_suffix}")
        parser_lib = parser_dir / f"{name}.{so_suffix}"
        if queries.exists():
            print(f"Deleting queries for {name}")
            rmrf(queries)
        if parser_lib.exists():
            print(f"Deleting parser library for {name}")
            parser_lib.unlink()
        if name in lockdata.repos:
            print(f"Removing {name} from lockfile")
            del lockdata.repos[name]

    print(f"Writing lockfile {lockfile_path}")
    write_lockfile(lockfile_path, lockdata)
    print("Uninstall complete!")


def list_parsers(rt_dir: Path, verbose: bool) -> None:
    lockfile_path = rt_dir / LOCKFILE_NAME
    lockdata = read_or_create_lockfile(lockfile_path)
    queries_dir = rt_dir / "queries"
    parser_dir = rt_dir / "parser"
    for name, data in sorted(lockdata.repos.items()):
        print(name)
        if not verbose:
            continue
        so_suffix = "wasm" if data.wasm else get_shared_lib_suffix()
        parser = parser_dir / f"{name}.{so_suffix}"
        if parser.exists():
            print(f"  parser: {parser}")
        else:
            print("  parser: ???")
        queries = queries_dir / name
        if queries.exists():
            print(f"  queries: {queries}")
        else:
            print("  queries: ???")
        inherited = get_inherited_queries(queries_dir, name)
        for ancestor in inherited:
            ancestor_queries = queries_dir / ancestor
            if ancestor_queries.exists():
                print(f"  inherits ({ancestor}): {ancestor_queries}")
            else:
                print(f"  inherits ({ancestor}): ???")


def get_inherited_queries(base_path: Path, name: str) -> set[str]:
    inherits = set()
    queries = base_path / name
    for query_file in queries.iterdir():
        if query_file.is_dir():
            continue
        with query_file.open("r") as f:
            line = f.readline()
            if not line.startswith("; inherits"):
                continue
            x = line.split(":")[1].strip().split(",")
            inherits |= set(x)
            for parent in x:
                if (base_path / parent).exists():
                    inherits |= get_inherited_queries(base_path, parent)
    return inherits


# ----LOCKFILE----


@dataclass
class RepoLockdata:
    rev: str
    src: str
    wasm: bool


@dataclass
class Lockdata:
    repos: dict[str, RepoLockdata]


def read_or_create_lockfile(path: Path) -> Lockdata:
    try:
        contents = path.read_text(encoding="UTF-8")
    except FileNotFoundError:
        path.write_text(json.dumps({"repos": {}}, indent=2))
        return Lockdata({})
    data = json.loads(contents)
    repos = {
        name: RepoLockdata(
            rev=repo_data["rev"], src=repo_data["src"], wasm=repo_data["wasm"]
        )
        for name, repo_data in data["repos"].items()
    }
    return Lockdata(repos)


def write_lockfile(path: Path, data: Lockdata) -> None:
    repos = {
        name: {"rev": r.rev, "src": r.src, "wasm": r.wasm}
        for name, r in sorted(data.repos.items(), key=lambda x: x[0])
    }
    dict_data = {"repos": repos}
    path.write_text(json.dumps(dict_data, indent=2))


# ----PAGE PARSER----


@dataclass
class ParserRepo:
    name: str
    url: str
    last_modified: date


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.repos: list[ParserRepo] = []
        self.in_td = False
        self.current_row: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "td":
            self.in_td = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr":
            if not self.current_row:
                return
            if self.current_row[3] != "-":
                self.repos.append(
                    ParserRepo(
                        name=self.current_row[0],
                        url="https://" + self.current_row[1],
                        last_modified=date.strptime(self.current_row[2], "%Y-%m-%d"),
                    )
                )
            self.current_row = []
        if tag == "td":
            self.in_td = False

    def handle_data(self, data: str) -> None:
        if self.in_td:
            self.current_row.append(data)


# ----MISC----


def get_shared_lib_suffix() -> str:
    system = platform.system()
    if system == "Windows":
        suffix = "dll"
    elif system == "Darwin":
        suffix = "dylib"
    elif system == "Linux":
        suffix = "so"
    else:
        raise RuntimeError(f"Unsupported OS: {system}")
    return suffix


def get_last_revision(src: str) -> str:
    result = subprocess.run(
        ["git", "ls-remote", src], capture_output=True, text=True, check=True
    )
    return result.stdout.split()[0]


def download_repo(url: str, archive_name: str, download_path: Path) -> Path:
    src_url = url + f"/archive/{archive_name}.zip"
    with urlopen(src_url) as response:
        zip_data = response.read()
    with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
        extracted_name = z.namelist()[0].split("/")[0]
        z.extractall(download_path)
    return download_path / extracted_name


def rmrf(top: Path) -> None:
    for root, dirs, files in top.walk(top_down=False):
        for name in files:
            (root / name).unlink()
        for name in dirs:
            (root / name).rmdir()
    top.rmdir()


def copy_into_clobber(src: Path, dst: Path) -> None:
    target = dst / src.name
    if target.exists():
        rmrf(target)
    shutil.copytree(src, target)


def get_config_home() -> Path:
    system = platform.system()
    if system == "Windows":
        config_home = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")
        )
        nvim_config = config_home / "nvim"
    else:
        xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        nvim_config = xdg_config / "nvim"
    return nvim_config


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def resolve_revision(repo_url: str, s: str) -> str:
    # Already a SHA
    if SHA_RE.fullmatch(s):
        return s.lower()

    output = subprocess.check_output(
        [
            "git",
            "ls-remote",
            "--heads",
            "--tags",
            repo_url,
            s,
            f"{s}^{{}}",
        ],
        text=True,
        stderr=subprocess.DEVNULL,
    )

    lines = [line.strip() for line in output.splitlines() if line.strip()]

    if not lines:
        raise ValueError(f"Could not resolve revision: {s}")
    for line in lines:
        sha, ref = line.split("\t", 1)
        if ref == f"refs/tags/{s}^{{}}":
            return sha
    for line in lines:
        sha, ref = line.split("\t", 1)
        if ref == f"refs/heads/{s}":
            return sha
    for line in lines:
        sha, ref = line.split("\t", 1)
        if ref == f"refs/tags/{s}":
            return sha
    raise ValueError(f"Could not resolve revision: {s}")


if __name__ == "__main__":
    main()
