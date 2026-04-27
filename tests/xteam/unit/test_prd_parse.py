from pathlib import Path

import pytest

from xteam_lib.prd import parse_prd


def test_parse_extracts_frontmatter_and_body(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    assert prd.frontmatter["title"] == "Add comment reactions"
    assert prd.frontmatter["business_type"] == "content_social"
    assert len(prd.frontmatter["features"]) == 2
    assert prd.body.startswith("# Add Comment Reactions")


def test_parse_fails_without_frontmatter(tmp_path: Path):
    bad = tmp_path / "no-fm.md"
    bad.write_text("# Just a heading\n\nno frontmatter here.\n")
    with pytest.raises(ValueError, match="frontmatter"):
        parse_prd(bad)


def test_parse_fails_with_unclosed_frontmatter(tmp_path: Path):
    bad = tmp_path / "bad-fm.md"
    bad.write_text("---\ntitle: x\n\nbody without closing fence\n")
    with pytest.raises(ValueError, match="frontmatter"):
        parse_prd(bad)
