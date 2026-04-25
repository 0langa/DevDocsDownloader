from __future__ import annotations

import asyncio
from pathlib import Path

from doc_ingest.config import load_config
from doc_ingest.models import TopicStats
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.sources.base import Document, LanguageCatalog
from doc_ingest.sources.dash import _convert_html as convert_dash_html
from doc_ingest.sources.devdocs import _convert_html as convert_devdocs_html
from doc_ingest.sources.mdn import _metadata_strings, _parse_frontmatter
from doc_ingest.validator import validate_output


def test_devdocs_cleanup_removes_navigation_and_rewrites_links() -> None:
    html = """
    <body>
      <nav>Global navigation</nav>
      <main class="content">
        <p>Read the <a href="../guide/install">install guide</a>.</p>
        <pre><code>print("ok")</code></pre>
        <table><tr><th>Name</th><th>Value</th></tr><tr><td>a</td><td>b</td></tr></table>
      </main>
      <footer>Footer noise</footer>
    </body>
    """

    markdown = convert_devdocs_html(html, "https://devdocs.io/python/library/path")

    assert "Global navigation" not in markdown
    assert "Footer noise" not in markdown
    assert "https://devdocs.io/python/guide/install" in markdown
    assert "print" in markdown
    assert "Name" in markdown and "Value" in markdown


def test_dash_cleanup_rewrites_relative_docset_links_and_preserves_external_links() -> None:
    html = """
    <html>
      <body>
        <div class="sidebar">Index</div>
        <article>
          <a href="Classes/Foo.html">Foo</a>
          <a href="https://example.invalid/external">External</a>
        </article>
      </body>
    </html>
    """

    markdown = convert_dash_html(html, "dash://Swift/index.html")

    assert "Index" not in markdown
    assert "dash://Swift/Classes/Foo.html" in markdown
    assert "https://example.invalid/external" in markdown


def test_markdown_link_rewriting_does_not_touch_code_spans_or_fences() -> None:
    html = """
    <main>
      <p><a href="relative/page">real link</a></p>
      <p><code>[sample](relative/code)</code></p>
      <pre><code>[fenced](relative/fence)</code></pre>
    </main>
    """

    markdown = convert_devdocs_html(html, "https://devdocs.io/lang/root")

    assert "(https://devdocs.io/lang/relative/page)" in markdown
    assert "[sample](relative/code)" in markdown
    assert "[fenced](relative/fence)" in markdown


def test_mdn_frontmatter_preserves_nested_yaml_and_lists() -> None:
    raw = """---
title: "Fetch API"
slug: Web/API/Fetch_API
page-type:
  - web-api-interface
status:
  - experimental
browser-compat:
  api.Fetch: true
---
# Body
"""

    meta, body, warning = _parse_frontmatter(raw)

    assert warning is None
    assert meta["title"] == "Fetch API"
    assert meta["slug"] == "Web/API/Fetch_API"
    assert _metadata_strings(meta["page-type"]) == ["web-api-interface"]
    assert meta["browser-compat"] == {"api.Fetch": True}
    assert body.strip() == "# Body"


def test_mdn_malformed_frontmatter_keeps_original_body() -> None:
    raw = "---\ntitle: [broken\n---\nBody"

    meta, body, warning = _parse_frontmatter(raw)

    assert meta == {}
    assert body == raw
    assert warning is not None


def test_validator_reports_relative_links_empty_targets_and_conversion_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "out.md"
    output.write_text(
        "\n".join(
            [
                "# Test Documentation",
                "",
                "## Metadata",
                "x" * 2100,
                "## Table of Contents",
                "## Documentation",
                "[relative](guide/page)",
                "![image](images/a.png)",
                "[empty]()",
                "<div>leftover</div>",
                "| A | B |",
                "| --- | --- |",
                "| only one |",
                ": definition artifact",
                "```python",
                "[not-a-link](relative/code)",
                "```",
            ]
        ),
        encoding="utf-8",
    )

    result = validate_output(
        language="Test",
        output_path=output,
        total_documents=1,
        topics=[TopicStats(topic="Reference", document_count=1)],
    )
    codes = {issue.code for issue in result.issues}

    assert "relative_link" in codes
    assert "relative_image" in codes
    assert "empty_link_target" in codes
    assert "html_leftover" in codes
    assert "malformed_table" in codes
    assert "definition_list_artifact" in codes


def test_pipeline_integration_preserves_rewritten_source_links(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    catalog = LanguageCatalog(source="devdocs", slug="fixture", display_name="Fixture")

    class Source:
        name = "devdocs"

        async def list_languages(self, *, force_refresh: bool = False):
            return [catalog]

        async def fetch(self, language, mode, diagnostics=None, **_kwargs):
            if diagnostics is not None:
                diagnostics.discovered += 1
                diagnostics.emitted += 1
            html = "<main><p><a href='guide/page'>Guide</a></p><p>" + ("content " * 400) + "</p></main>"
            yield Document(
                topic="Reference",
                slug="doc",
                title="Doc",
                markdown=convert_devdocs_html(html, "https://devdocs.io/fixture/doc"),
                source_url="https://devdocs.io/fixture/doc",
                order_hint=0,
            )

    report = asyncio.run(
        pipeline._run_language(
            source=Source(),
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    output = (config.paths.markdown_dir / "fixture" / "fixture.md").read_text(encoding="utf-8")
    assert report.failures == []
    assert "https://devdocs.io/fixture/guide/page" in output
    assert report.validation is not None
    assert "relative_link" not in {issue.code for issue in report.validation.issues}
