"""Generate an ATS-safe resume as .pdf, .docx and plain text.

The content comes from `resume/resume.yaml`, which is gitignored - a resume is
personal data and does not belong in a shared repository. Copy
`resume.example.yaml` to `resume.yaml` and fill it in; this file only decides
how it is laid out.

    python resume/build_resume.py          .docx + .txt
    python resume/build_resume.py --pdf    also the .pdf

The PDF is the one-column LaTeX layout of the resume it was made from (Times
9pt, ruled section headings, dates on the right, bold metrics, links), printed
by the Chromium that Playwright already installs. naukri/jobs/tailor.py builds
one per job with this, so what an employer receives looks exactly like your
own resume.

ATS parsers read a document as a linear stream of text. Anything that breaks
that stream - tables, text boxes, multi-column layouts, headers and footers,
images, icon fonts - either scrambles the reading order or is dropped outright.
An earlier version of this resume lost its project labels exactly that way:
they parsed *after* their own descriptions.

So everything here is single-column paragraphs. In the .docx, section rules are
paragraph borders rather than table edges, dates sit on a right tab stop rather
than in a right-hand column, and bullets are literal characters with a hanging
indent instead of Word list numbering, which some parsers strip. The PDF is
real text in reading order (no images), so the same holds there.

Text may mark **bold** phrases (the metrics in a bullet); the .txt drops the
marks.
"""
import html
import re
import sys
import threading
from pathlib import Path

import yaml
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Inches, RGBColor

OUT = Path(__file__).resolve().parent
CONTENT = OUT / "resume.yaml"
EXAMPLE = OUT / "resume.example.yaml"
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


class ResumeError(RuntimeError):
    """resume.yaml is missing or does not have what the layout needs."""


def load(path: Path = CONTENT) -> dict:
    """Read resume.yaml and check it has enough to build a resume from.

    The checks are deliberately loud. A missing `experience` key would
    otherwise produce a clean-looking one-page resume with no jobs on it, and
    that is the kind of thing you notice after sending it somewhere.
    """
    if not path.exists():
        raise ResumeError(
            f"No {path.name} in {path.parent}.\n"
            f"  Copy the template and fill it in:\n"
            f"      cp resume/{EXAMPLE.name} resume/{path.name}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ResumeError(f"{path.name} is not valid YAML: {exc}")
    if not isinstance(data, dict):
        raise ResumeError(f"{path.name} must be a YAML mapping.")

    missing = [k for k in ("name", "title", "summary", "experience") if not data.get(k)]
    if missing:
        raise ResumeError(
            f"{path.name} is missing: {', '.join(missing)}. "
            f"See {EXAMPLE.name} for what each field holds.")

    for index, job in enumerate(data["experience"], start=1):
        absent = [k for k in ("title", "org", "dates", "bullets") if not job.get(k)]
        if absent:
            raise ResumeError(
                f"{path.name}: experience entry {index} "
                f"({job.get('title') or job.get('org') or 'unnamed'}) "
                f"is missing: {', '.join(absent)}")
    return data


def plain(text) -> str:
    """Text without the **bold** marks."""
    return _BOLD.sub(r"\1", str(text or ""))


def _pairs(rows: list, first: str, second: str) -> list[tuple[str, str]]:
    """Accept either a mapping or a two-item list per row.

    The example file uses mappings because they are self-documenting, but a
    plain `- [Languages, "Python, SQL"]` is less to type and works too.
    """
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            out.append((str(row.get(first) or ""), str(row.get(second) or "")))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            out.append((str(row[0]), str(row[1])))
    return out


def projects_of(data: dict) -> list[dict]:
    """Projects as {name, year, tech, bullets, description}. Old rows (label + description) still work."""
    out = []
    for row in data.get("projects") or []:
        if isinstance(row, dict):
            out.append({"name": str(row.get("name") or row.get("label") or ""), "year": str(row.get("year") or ""),
                        "tech": str(row.get("tech") or ""), "bullets": [str(b) for b in row.get("bullets") or []],
                        "description": str(row.get("description") or "")})
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            out.append({"name": str(row[0]), "year": "", "tech": "", "bullets": [], "description": str(row[1])})
    return out


def education_of(data: dict) -> list[dict]:
    out = []
    for entry in data.get("education") or []:
        if isinstance(entry, dict):
            out.append({k: str(entry.get(k) or "") for k in ("degree", "institution", "years", "grade")})
        else:
            degree, school, years = (list(entry) + [None, None])[:3]
            out.append({"degree": str(degree or ""), "institution": str(school or ""), "years": str(years or ""), "grade": ""})
    return out


# ---------------------------------------------------------------- .docx

INK = RGBColor(0, 0, 0)
BODY_FONT = "Times New Roman"
HEAD_FONT = "Arial"


def style_base(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    normal.font.size = Pt(9)
    normal.font.color.rgb = INK
    pf = normal.paragraph_format
    pf.space_after = Pt(0)
    pf.space_before = Pt(0)
    pf.line_spacing = 1.0

    for section in doc.sections:
        section.page_height = Inches(11.69)          # A4, as the original
        section.page_width = Inches(8.27)
        section.top_margin = Inches(0.45)
        section.bottom_margin = Inches(0.45)
        section.left_margin = Inches(0.45)
        section.right_margin = Inches(0.5)


def _text_width(doc: Document):
    s = doc.sections[0]
    return s.page_width - s.left_margin - s.right_margin


def _runs(p, text: str, size=None, italic=False, bold=False) -> None:
    """Add text to a paragraph, **bold** marks as bold runs."""
    parts = _BOLD.split(str(text))
    for i, part in enumerate(parts):
        if not part:
            continue
        run = p.add_run(part)
        run.bold = bold or i % 2 == 1
        run.italic = italic
        if size:
            run.font.size = Pt(size)


def bottom_rule(paragraph) -> None:
    """Underline a heading with a paragraph border, not a table edge."""
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "4")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    borders.append(bottom)
    p_pr.append(borders)


def heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text.upper())
    run.bold = True
    run.font.name = HEAD_FONT
    run.font.size = Pt(9)
    bottom_rule(p)


def bullet(doc: Document, text: str) -> None:
    """Literal bullet with a hanging indent - Word list numbering is often stripped."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Inches(0.16)
    pf.first_line_indent = Inches(-0.12)
    p.add_run("•  ")
    _runs(p, text)


def left_right(doc: Document, left: str, right: str, bold_left=True) -> None:
    """'Title ....... dates' on one line: a right tab stop, not a table."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.tab_stops.add_tab_stop(_text_width(doc), WD_TAB_ALIGNMENT.RIGHT)
    _runs(p, left, bold=bold_left)
    if right:
        p.add_run("\t" + right)


def hyperlink(paragraph, text: str, url: str) -> None:
    part = paragraph.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                          is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def basename(data: dict) -> str:
    """File stem for the outputs. Derived from the name unless one is given."""
    stated = str(data.get("output_basename") or "").strip()
    if stated:
        return stated
    slug = "_".join(part.capitalize() for part in str(data["name"]).split())
    return f"{slug}_Resume" if slug else "Resume"


def build(data: dict) -> Path:
    doc = Document()
    style_base(doc)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(data["name"])
    run.bold = True
    run.font.name = HEAD_FONT
    run.font.size = Pt(18)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(plain(data["title"]))
    run.italic = True
    run.font.name = HEAD_FONT
    run.font.size = Pt(9.5)

    lines = [str(line) for line in data.get("contact") or []]
    links = data.get("links") or []
    for i, line in enumerate(lines or [""]):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run(line)
        if i == len(lines or [""]) - 1:          # links go on the last contact line, as on the original
            for link in links:
                p.add_run(" | " if p.text else "")
                hyperlink(p, str(link.get("text") or link.get("url")), str(link.get("url")))

    heading(doc, "Professional Summary")
    p = doc.add_paragraph()
    _runs(p, data["summary"])

    skills = _pairs(data.get("skills"), "label", "items")
    if skills:
        heading(doc, "Technical Skills")
        for label, items in skills:
            p = doc.add_paragraph()
            p.add_run(f"{label}: ").bold = True
            _runs(p, items)

    heading(doc, "Professional Experience")
    for job in data["experience"]:
        left_right(doc, f"{job['title']}, {job['org']}", str(job["dates"]))
        sub = " | ".join(str(bit) for bit in (job.get("loc"), job.get("tech")) if bit)
        if sub:
            p = doc.add_paragraph()
            _runs(p, sub, italic=True)
        for line in job["bullets"]:
            bullet(doc, line)

    projects = projects_of(data)
    if projects:
        heading(doc, "Projects")
        for pr in projects:
            left_right(doc, pr["name"], pr["year"])
            if pr["tech"]:
                p = doc.add_paragraph()
                _runs(p, pr["tech"], italic=True)
            for line in pr["bullets"] or ([pr["description"]] if pr["description"] else []):
                bullet(doc, line)

    education = education_of(data)
    if education:
        heading(doc, "Education")
        for e in education:
            left_right(doc, e["degree"], e["years"])
            p = doc.add_paragraph()
            p.add_run(e["institution"])
            if e["grade"]:
                p.add_run(" | " + e["grade"]).bold = True

    if data.get("certifications"):
        heading(doc, "Certifications & Achievements")
        for line in data["certifications"]:
            p = doc.add_paragraph()
            _runs(p, str(line))

    path = OUT / f"{basename(data)}.docx"
    doc.save(path)
    return path


# ---------------------------------------------------------------- .pdf

_CSS = """
@page { size: A4; margin: 30pt 30pt 28pt 32pt; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; }
body { margin: 0; font-family: "Times New Roman", "Nimbus Roman", Times, serif; font-size: 9pt;
       line-height: 1.19; color: #000; zoom: var(--scale, 1);
       letter-spacing: -.03pt; }   /* Chromium Times runs a hair wider than LaTeX; word-spacing would merge words for ATS */
a { color: inherit; text-decoration: underline; text-decoration-thickness: .4pt; text-underline-offset: 1.5pt; }
.name { font-family: Arial, Helvetica, sans-serif; font-weight: 700; font-size: 19.5pt; color: #1f3a68;
        line-height: 1.05; letter-spacing: .1pt; }
.title { font-family: Arial, Helvetica, sans-serif; font-style: italic; font-size: 9.4pt; color: #555; margin-top: 1.5pt; }
.contact { margin-top: 2pt; }
.contact .sep { margin: 0 4pt; }
.contact a { color: #1f3a68; }
h2 { font-family: Arial, Helvetica, sans-serif; font-weight: 700; font-size: 9pt; color: #1f3a68; margin: 5pt 0 4pt;
     padding-bottom: 4.5pt; border-bottom: .6pt solid #1f3a68; text-transform: uppercase; letter-spacing: .1pt; }
.row { display: flex; justify-content: space-between; gap: 12pt; margin-top: 2.5pt; }
.row .l { font-weight: 700; } .row .r { white-space: nowrap; color: #555; }
.sub { font-style: italic; color: #555; }
ul { margin: 1pt 0 0; padding: 0; list-style: none; }
li { padding-left: 17pt; text-indent: -7pt; margin-top: .5pt; }
li::before { content: "\\2022"; display: inline-block; width: 7pt; text-indent: 0; }
.skills div { margin-top: 1.6pt; }
.skills div:first-child { margin-top: 0; }
.certs div { margin-top: .6pt; }
"""


def _h(text) -> str:
    """HTML-escaped, with **bold** marks as <b>."""
    return _BOLD.sub(r"<b>\1</b>", html.escape(str(text or ""), quote=False))


def to_html(data: dict) -> str:
    out = [f'<div class="name">{html.escape(data["name"])}</div>', f'<div class="title">{html.escape(plain(data["title"]))}</div>']
    contact = [html.escape(str(c)) for c in data.get("contact") or []]
    links = [f'<a href="{html.escape(str(l.get("url")))}">{html.escape(str(l.get("text") or l.get("url")))}</a>'
             for l in data.get("links") or []]
    if contact or links:
        last = '<span class="sep">|</span>'.join(x for x in ([contact[-1]] if contact else []) + links)
        for c in contact[:-1]:
            out.append(f'<div class="contact">{c.replace(" | ", '<span class="sep">|</span>')}</div>')
        out.append(f'<div class="contact">{last.replace(" | ", '<span class="sep">|</span>')}</div>')

    out += ["<h2>Professional Summary</h2>", f"<div>{_h(data['summary'])}</div>"]
    skills = _pairs(data.get("skills"), "label", "items")
    if skills:
        out.append('<h2>Technical Skills</h2><div class="skills">')
        out += [f"<div><b>{html.escape(label)}:</b> {_h(items)}</div>" for label, items in skills]
        out.append("</div>")

    out.append("<h2>Professional Experience</h2>")
    for job in data["experience"]:
        out.append(f'<div class="row"><span class="l">{_h(job["title"])}, {_h(job["org"])}</span>'
                   f'<span class="r">{_h(job["dates"])}</span></div>')
        sub = " | ".join(str(bit) for bit in (job.get("loc"), job.get("tech")) if bit)
        if sub:
            out.append(f'<div class="sub">{_h(sub)}</div>')
        out.append("<ul>" + "".join(f"<li>{_h(b)}</li>" for b in job["bullets"]) + "</ul>")

    projects = projects_of(data)
    if projects:
        out.append("<h2>Projects</h2>")
        for pr in projects:
            out.append(f'<div class="row"><span class="l">{_h(pr["name"])}</span><span class="r">{_h(pr["year"])}</span></div>')
            if pr["tech"]:
                out.append(f'<div class="sub">{_h(pr["tech"])}</div>')
            lines = pr["bullets"] or ([pr["description"]] if pr["description"] else [])
            out.append("<ul>" + "".join(f"<li>{_h(b)}</li>" for b in lines) + "</ul>")

    education = education_of(data)
    if education:
        out.append("<h2>Education</h2>")
        for e in education:
            out.append(f'<div class="row"><span class="l">{_h(e["degree"])}</span><span class="r">{_h(e["years"])}</span></div>')
            out.append(f"<div>{_h(e['institution'])}" + (f" <b>| {_h(e['grade'])}</b>" if e["grade"] else "") + "</div>")

    if data.get("certifications"):
        out.append('<h2>Certifications &amp; Achievements</h2><div class="certs">')
        out += [f"<div>{_h(c)}</div>" for c in data["certifications"]]
        out.append("</div>")

    title = html.escape(f"{data['name'].title()} - {plain(data['title']).split('|')[0].strip()} Resume")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>'
            f"<style>{_CSS}</style></head><body>{''.join(out)}</body></html>")


def _pages(pdf: bytes) -> int:
    import io
    from pypdf import PdfReader
    return len(PdfReader(io.BytesIO(pdf)).pages)


def build_pdf(data: dict, path: Path | None = None, shrink=None, scales=(1.0, 0.97, 0.94)) -> tuple[Path, int, int]:
    """Print the resume to PDF in the original's layout -> (path, pages, times shrink() was called).

    One page is the goal: each scale in `scales` is tried first (a few percent smaller still
    reads as the same resume), then `shrink(data)` - which drops the least useful line and
    returns False when nothing is left to drop - until it fits. Runs Chromium on its own
    thread, so it also works from inside the applier's Playwright session.
    """
    path = Path(path or OUT / f"{basename(data)}.pdf")
    box: dict = {}

    def run():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page()
                    dropped = 0
                    while True:
                        page.set_content(to_html(data), wait_until="load")
                        for scale in scales:
                            page.evaluate(f"document.body.style.setProperty('--scale', '{scale}')")
                            pdf = page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
                            pages = _pages(pdf)
                            if pages <= 1:
                                break
                        if pages <= 1 or shrink is None or not shrink(data):
                            break
                        dropped += 1
                finally:
                    browser.close()
            path.write_bytes(pdf)
            box["v"] = (path, pages, dropped)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            box["e"] = exc

    t = threading.Thread(target=run, name="resume-pdf")
    t.start()
    t.join()
    if "e" in box:
        raise box["e"]
    return box["v"]


# ---------------------------------------------------------------- .txt

def build_text(data: dict) -> Path:
    """Plain text for portals that mangle uploads and want a paste instead.

    This is also the file the interview-prep module reads, and its ALL-CAPS
    headings are load-bearing there: naukri/interview/profile.py splits on them
    to tell resume narrative (strong evidence for a skill) from a skills list
    (weaker). Renaming a heading here quietly downgrades your own evidence.
    """
    links = " | ".join(str(l.get("url")) for l in data.get("links") or [])
    lines = [data["name"], plain(data["title"]), *(str(c) for c in data.get("contact") or []),
             *([links] if links else []), "", "PROFESSIONAL SUMMARY", plain(data["summary"])]

    skills = _pairs(data.get("skills"), "label", "items")
    if skills:
        lines += ["", "TECHNICAL SKILLS"]
        lines += [f"{label}: {plain(items)}" for label, items in skills]

    lines += ["", "PROFESSIONAL EXPERIENCE"]
    for job in data["experience"]:
        lines += ["", f"{job['title']}, {job['org']} | {job['dates']}",
                  " | ".join(str(bit) for bit in (job.get("loc"), job.get("tech")) if bit)]
        lines += [f"- {plain(b)}" for b in job["bullets"]]

    projects = projects_of(data)
    if projects:
        lines += ["", "PROJECTS"]
        for pr in projects:
            lines += [" | ".join(x for x in (pr["name"], pr["year"]) if x)] + ([pr["tech"]] if pr["tech"] else [])
            lines += [f"- {plain(b)}" for b in pr["bullets"] or ([pr["description"]] if pr["description"] else [])]

    education = education_of(data)
    if education:
        lines += ["", "EDUCATION"]
        for e in education:
            lines.append(" | ".join(b for b in (e["degree"], e["institution"], e["years"], e["grade"]) if b))

    if data.get("certifications"):
        lines += ["", "CERTIFICATIONS & ACHIEVEMENTS"]
        lines += [f"- {plain(c)}" for c in data["certifications"]]

    path = OUT / f"{basename(data)}.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    try:
        data = load()
    except ResumeError as exc:
        print(f"\n  {exc}\n")
        return 2
    docx_path = build(data)
    txt_path = build_text(data)
    words = len(txt_path.read_text(encoding="utf-8").split())
    print(f"wrote {docx_path}")
    print(f"wrote {txt_path}")
    if "--pdf" in sys.argv[1:]:
        pdf_path, pages, _ = build_pdf(data)
        print(f"wrote {pdf_path} ({pages} page{'s' if pages != 1 else ''})")
    print(f"word count: {words}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
