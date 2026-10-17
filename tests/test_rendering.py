"""Update-notes markdown and build images."""
import io

import aiohttp
import pytest
from PIL import Image

import subject

md = subject.patch_notes_markdown


# --- Update notes markdown -------------------------------------------------


def test_inline_styles():
    assert md("<p><strong>Bold</strong> <b>also</b> <em>it</em> <i>al</i> <s>gone</s></p>") == (
        "**Bold** **also** *it* *al* ~~gone~~"
    )


def test_emphasis_keeps_spaces_outside_markers():
    # "*Guild Wars 2 *" doesn't render as italics in Discord
    assert md("<p>Get <em>Guild Wars 2 </em>today</p>") == "Get *Guild Wars 2* today"


def test_empty_emphasis_is_dropped():
    assert md("<p>A<strong> </strong>B<em></em></p>") == "A B"


def test_headings():
    assert md("<h1><span>Release Notes</span></h1><h2>General</h2><h4>Items</h4>") == (
        "**Release Notes**\n\n*General*\n\n*Items*"
    )


def test_links():
    assert md('<p>See <a href="https://help.guildwars2.com/x" rel="external">here</a>.</p>') == (
        "See [here](https://help.guildwars2.com/x)."
    )
    assert md('<p>Mail <a href="mailto:support@arena.net">support@arena.net</a></p>') == (
        "Mail support@arena.net"
    )
    assert md('<p><a href="https://example.com/"></a></p>') == "<https://example.com/>"
    assert md('<p><a href="/relative">text</a></p>') == "text"


def test_lists():
    html = """
    <ul type="disc">
      <li><span>First item.</span></li>
      <li>
          Second item, with
          extra whitespace.
      </li>
      <li>Parent
        <ul><li>Child one</li><li>Child two</li></ul>
      </li>
    </ul>
    <ol><li>One</li><li>Two</li></ol>
    """
    child = "  ◦ "
    assert md(html) == "\n".join([
        "• First item.",
        "• Second item, with extra whitespace.",
        "• Parent",
        child + "Child one",
        child + "Child two",
        "",
        "1. One",
        "2. Two",
    ])


def test_paragraph_whitespace_is_collapsed():
    html = "<p>\n\tOnce again,   the gates&nbsp;open.\n</p>\n\n\n<p>Next.</p>"
    # &nbsp; becomes a plain space, as in the old html2markdown pipeline
    assert md(html) == "Once again, the gates open.\n\nNext."


def test_line_breaks():
    assert md("<p>Line one<br>Line two</p>") == "Line one\nLine two"


def test_markdown_characters_are_escaped():
    assert md("<p>*Footnote_with_underscores ~ | `code`</p>") == (
        "\\*Footnote\\_with\\_underscores \\~ \\| \\`code\\`"
    )


def test_images_scripts_and_comments_are_dropped():
    assert md('<p>Text<img src="x.png"><script>alert(1)</script><!-- note --></p>') == "Text"


def test_forum_post_shape():
    # Shape of a real update-notes post: spans everywhere, fake bullets
    html = """
    <h1><span>10/13/2026—October 13 Release Notes</span></h1>
    <p><strong>Note to users of third-party programs:</strong> The game may not launch.</p>
    <h2><span>Release Highlights</span></h2>
    <p><span><span>·<span>         </span></span></span><span>Halloween returns!</span></p>
    <h4><strong>General</strong></h4>
    <ul><li><span>Fixed an issue.</span></li></ul>
    """
    assert md(html) == "\n\n".join([
        "**10/13/2026—October 13 Release Notes**",
        "**Note to users of third-party programs:** The game may not launch.",
        "*Release Highlights*",
        "· Halloween returns!",
        "***General***",
        "• Fixed an issue.",
    ])


# --- Build images ----------------------------------------------------------


def png(size, color="red"):
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, "png")
    return buffer.getvalue()


def specialization(spec_id):
    major = [spec_id * 100 + i for i in range(9)]
    minor = [spec_id * 100 + 50 + i for i in range(3)]
    traits = {t: {"icon": f"https://render/trait/{t}.png"} for t in major + minor}
    spec = {
        "name": f"Spec {spec_id}",
        "background": f"https://render/background/{spec_id}.png",
        "major_traits": major,
        "minor_traits": minor,
    }
    return {"spec_doc": spec, "active_traits": major[::4], "trait_docs": traits}


SKILLS = [{"icon": f"https://render/skill/{i}.png"} for i in range(5)]


def images_for(specs, skills):
    images = {s["icon"]: png((64, 64)) for s in skills}
    for d in specs:
        images[d["spec_doc"]["background"]] = png((645, 256), "blue")
        for trait in d["trait_docs"].values():
            images[trait["icon"]] = png((64, 64), "green")
    return images


async def test_build_image_with_skills_and_specializations():
    specs = [specialization(i) for i in (1, 2, 3)]
    session = subject.FakeImageSession(images_for(specs, SKILLS))
    image = Image.open(io.BytesIO(await subject.render_build(session, specs, SKILLS)))
    # 64px skill bar plus three 135px specialization strips
    assert image.size == (645, 64 + 3 * 135)
    assert image.format == "PNG"


async def test_build_image_with_skills_only():
    session = subject.FakeImageSession(images_for([], SKILLS))
    image = Image.open(io.BytesIO(await subject.render_build(session, [], SKILLS)))
    assert image.size == (645, 64)


async def test_empty_build_has_no_image():
    session = subject.FakeImageSession({})
    assert await subject.render_build(session, [], []) is None
    assert session.requests == []


async def test_build_images_are_downloaded_once():
    skills = SKILLS + SKILLS[:2]
    specs = [specialization(1)]
    session = subject.FakeImageSession(images_for(specs, skills))
    await subject.render_build(session, specs, skills)
    assert len(session.requests) == len(set(session.requests)) == 5 + 1 + 12


async def test_failed_image_download_raises():
    specs = [specialization(1)]
    images = images_for(specs, SKILLS)
    del images[SKILLS[0]["icon"]]
    with pytest.raises(aiohttp.ClientResponseError):
        await subject.render_build(subject.FakeImageSession(images), specs, SKILLS)
