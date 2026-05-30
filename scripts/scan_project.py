import time
from pathlib import Path


def scan_project(root=".", ignore=None):
    """Scan project directory, return file stats sorted by size."""
    if ignore is None:
        ignore = {".git", "__pycache__", "node_modules", ".venv", ".claude"}
    results = []
    root = Path(root)
    for f in root.rglob("*"):
        if f.is_file() and not any(p in f.parts for p in ignore):
            stat = f.stat()
            results.append(
                {
                    "path": str(f.relative_to(root)),
                    "size_kb": round(stat.st_size / 1024, 1),
                    "ext": f.suffix or "(none)",
                }
            )
    results.sort(key=lambda x: x["size_kb"], reverse=True)
    return results


if __name__ == "__main__":
    t0 = time.time()
    files = scan_project(".")
    print(f"Scanned {len(files)} files in {time.time() - t0:.2f}s")
    for f in files[:10]:
        print(f"  {f['size_kb']:>8} KB  {f['ext']:<8} {f['path']}")
