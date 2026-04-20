from __future__ import annotations

import json
from pathlib import Path

from doc_ingest.config import load_config
from doc_ingest.parser import parse_language_file
from doc_ingest.utils.filesystem import read_json, write_json
from doc_ingest.utils.urls import normalize_url


def build_manifest() -> dict[str, dict[str, object]]:
    config = load_config()
    entries = parse_language_file(config.paths.input_file)
    manifests: dict[str, dict[str, object]] = {}

    for entry in entries:
        state_path = config.paths.state_dir / f"{entry.slug}.json"
        discovered_path = config.paths.crawl_cache_dir / f"{entry.slug}.json"
        state = read_json(state_path, {"processed": {}, "failed": {}})
        discovered = read_json(discovered_path, {"urls": {}, "roots": []})

        processed_urls = {normalize_url(url) for url in state.get("processed", {}).keys()}
        failed_urls = {normalize_url(url) for url in state.get("failed", {}).keys()}
        discovered_urls = {normalize_url(url) for url in discovered.get("urls", {}).keys()}
        skip_urls = sorted(processed_urls | failed_urls)

        manifests[entry.slug] = {
            "language": entry.name,
            "slug": entry.slug,
            "processed": sorted(processed_urls),
            "failed": sorted(failed_urls),
            "discovered": sorted(discovered_urls),
            "skip": skip_urls,
            "counts": {
                "processed": len(processed_urls),
                "failed": len(failed_urls),
                "discovered": len(discovered_urls),
                "skip": len(skip_urls),
            },
        }

    return manifests


def main() -> None:
    config = load_config()
    manifest = {
        "generated_from": str(config.paths.root),
        "languages": build_manifest(),
    }
    output_path = config.paths.cache_dir / "skip_manifest.json"
    write_json(output_path, manifest)
    print(f"Wrote skip manifest to {output_path}")
    print(json.dumps({slug: data["counts"] for slug, data in manifest["languages"].items()}, indent=2))


if __name__ == "__main__":
    main()