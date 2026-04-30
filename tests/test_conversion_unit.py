from __future__ import annotations

import pytest

from doc_ingest.conversion import (
    DASH_PROFILE,
    DEVDOCS_PROFILE,
    convert_html_to_markdown,
    resolve_source_link,
    rewrite_markdown_links,
)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<main><h1>Title</h1><p>Body</p></main>", "# Title"),
        ("<main><ul><li>One</li><li>Two</li></ul></main>", "* One"),
        ("<main><pre><code>print('x')</code></pre></main>", "```"),
        (
            "<main><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table></main>",
            "| A | B |",
        ),
        ("<main><ol><li>Outer<ul><li>Inner</li></ul></li></ol></main>", "Inner"),
    ],
)
def test_convert_html_to_markdown_handles_common_structures(html: str, expected: str) -> None:
    markdown = convert_html_to_markdown(html, base_url="https://example.com/docs/", profile=DEVDOCS_PROFILE)
    assert expected in markdown


def test_convert_html_to_markdown_prefers_selected_content_root_and_strips_noise() -> None:
    html = """
    <html>
      <body>
        <nav>ignore me</nav>
        <aside>and me</aside>
        <main>
          <h1>Docs</h1>
          <p>Keep this body.</p>
          <footer>not this</footer>
        </main>
      </body>
    </html>
    """
    markdown = convert_html_to_markdown(html, base_url="https://example.com/docs/", profile=DEVDOCS_PROFILE)
    assert "Docs" in markdown
    assert "Keep this body." in markdown
    assert "ignore me" not in markdown
    assert "not this" not in markdown


def test_convert_html_to_markdown_can_fall_back_to_body_for_dash_profile() -> None:
    html = "<body><h1>Dash Root</h1><p>Only body exists.</p></body>"
    markdown = convert_html_to_markdown(html, base_url="dash://python/index.html", profile=DASH_PROFILE)
    assert "# Dash Root" in markdown
    assert "Only body exists." in markdown


def test_rewrite_markdown_links_skips_code_fences_and_code_spans() -> None:
    markdown = """
[Doc](guide/page)

`[Inline](stay/raw)`

```md
[Fence](stay/raw)
```
""".strip()
    rewritten = rewrite_markdown_links(markdown, base_url="https://example.com/docs/")
    assert "[Doc](https://example.com/docs/guide/page)" in rewritten
    assert "`[Inline](stay/raw)`" in rewritten
    assert "[Fence](stay/raw)" in rewritten


def test_rewrite_markdown_links_handles_protocol_relative_and_anchor_only_links() -> None:
    markdown = "[CDN](//cdn.example.com/lib.js)\n[Anchor](#section)"
    rewritten = rewrite_markdown_links(markdown, base_url="https://example.com/docs/")
    assert "[CDN](https://cdn.example.com/lib.js)" in rewritten
    assert "[Anchor](#section)" in rewritten


@pytest.mark.parametrize(
    ("target", "base_url", "expected"),
    [
        ("guide/page", "https://example.com/docs/", "https://example.com/docs/guide/page"),
        ("https://upstream.example.com/ref", "https://example.com/docs/", "https://upstream.example.com/ref"),
        ("dash://python/path", "dash://python/index.html", "dash://python/path"),
        ("topic.html", "dash://python/guide/index.html", "dash://python/guide/topic.html"),
        (" malformed value ", "https://example.com/docs/", "https://example.com/docs/malformed value"),
    ],
)
def test_resolve_source_link_handles_relative_absolute_dash_and_malformed_inputs(
    target: str,
    base_url: str,
    expected: str,
) -> None:
    assert resolve_source_link(target, base_url=base_url) == expected
