from src.research.fetcher import extract_text_from_html


SAMPLE_HTML = """
<html>
  <head>
    <title>  Acme ships  Model X2  </title>
    <style>.a{color:red}</style>
    <script>var tracking = 1;</script>
  </head>
  <body>
    <nav>Home About Contact</nav>
    <article>
      <h1>Acme ships Model X2</h1>
      <p>Acme released Model&nbsp;X2 today with open weights.</p>
      <p>It scores 71% on the SWE-bench benchmark.</p>
    </article>
    <footer>Copyright 2026</footer>
  </body>
</html>
"""


def test_extract_title_and_body():
    title, text = extract_text_from_html(SAMPLE_HTML)
    assert title == "Acme ships Model X2"
    assert "open weights" in text
    assert "71% on the SWE-bench" in text


def test_extract_strips_boilerplate():
    _, text = extract_text_from_html(SAMPLE_HTML)
    assert "tracking" not in text          # <script> dropped
    assert "color:red" not in text         # <style> dropped
    assert "Home About Contact" not in text  # <nav> dropped
    assert "Copyright 2026" not in text    # <footer> dropped


def test_extract_respects_max_chars():
    long_html = "<p>" + ("word " * 5000) + "</p>"
    _, text = extract_text_from_html(long_html, max_chars=200)
    assert len(text) <= 210  # max_chars + ellipsis slack
    assert text.endswith("…")


def test_extract_handles_malformed_html():
    title, text = extract_text_from_html("<p>unclosed <b>bold and <i>more")
    assert "unclosed" in text
    assert "bold" in text
