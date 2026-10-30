#!/usr/bin/env python3
"""Check owned Markdown links against the published file set, not local artifacts."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]


def main():
    probe = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                           capture_output=True, text=True)
    if probe.returncode == 0 and Path(probe.stdout.strip()).resolve() == ROOT:
        names = set(subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT).decode().split("\0")) - {""}
    else:
        # A source ZIP/tar has no ignored local research files to hide bad links.
        names = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
    errors, checked = [], 0
    for name in sorted(names):
        if not name.endswith(".md") or any(part in name for part in
                ("/third_party/", "/external/", "/reference/")):
            continue  # Preserved third-party and original-project documentation.
        source = ROOT / name
        text = re.sub(r"```.*?```", "", source.read_text(encoding="utf-8"), flags=re.S)
        for target in re.findall(r"\]\(([^)]+)\)", text):
            target = target.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            checked += 1
            path = (source.parent / unquote(parsed.path)).resolve()
            try:
                relative = path.relative_to(ROOT).as_posix()
            except ValueError:
                errors.append(f"{name}: link escapes checkout: {target}")
                continue
            if relative not in names and not any(p.startswith(relative + "/") for p in names):
                errors.append(f"{name}: link is absent from published files: {target}")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Public Markdown links passed: {checked} local targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
