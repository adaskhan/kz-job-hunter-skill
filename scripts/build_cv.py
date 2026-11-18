#!/usr/bin/env python3
"""
build_cv.py — собирает одностраничное ATS-friendly резюме в PDF из resume.md (только stdlib).

    python3 build_cv.py --in ~/.kz-job-hunter/resume.md --out ~/Downloads/Name_CV.pdf

PDF печатается через установленный Chrome / Chromium / Edge / Brave в headless-режиме.
Если браузера нет — сохраняется HTML, который можно открыть и «Напечатать → Сохранить как PDF».

Формат resume.md:

    # Имя Фамилия — любая подпись (в PDF идёт только имя)
    Строка-заголовок под именем: роль · стек · город · формат
    Контакты: телефон · email · linkedin.com/in/... · github.com/...

    ## Experience
    **Должность — Компания** (Город, Mon YYYY – Present)
    - достижение

    ## Projects
    **Проект** (YYYY – Present) — стек
    - что сделано

    ## Technical Skills
    - Группа: навык, навык

    ## Education
    Университет — Степень (Город, Mon YYYY – Mon YYYY)

Заголовки разделов могут быть по-русски («Опыт работы», «Навыки», «Образование», «Проекты»).
"""
import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile

BROWSERS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser",
    "chrome", "msedge",
]

ENTRY_RE = re.compile(r"^\*{0,2}(?P<a>.+?)\s+[—–-]\s+(?P<b>.+?)\*{0,2}\s*\((?P<paren>[^()]+)\)\s*$")
PROJECT_RE = re.compile(r"^\*\*(?P<name>.+?)\*\*\s*\((?P<dates>[^()]+)\)\s*(?:[—–-]\s*(?P<stack>.+))?$")
DATE_HINT = re.compile(r"\b(19|20)\d{2}\b|present|now|наст|по\s+н\.?в", re.I)
LINK_RE = re.compile(r"(?P<email>[\w.+-]+@[\w-]+\.[\w.]+)|(?P<url>(?:https?://)?(?:www\.)?"
                     r"(?:linkedin\.com|github\.com|gitlab\.com|t\.me|hh\.(?:kz|ru)|[\w-]+\.(?:dev|io|me|kz))/?[\w./-]*)")

CSS = """
@page { size: A4; margin: 9mm 12mm 8mm 12mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #fff; }
body { font-family: "Charter", "Georgia", "Times New Roman", serif; font-size: %(fs).2fpt; line-height: 1.24; color: #111; }
a { color: #111; text-decoration: underline; text-underline-offset: 1.5pt; text-decoration-thickness: 0.4pt; }
header { text-align: center; margin-bottom: 4pt; }
h1 { font-size: 22pt; font-weight: 700; margin: 0 0 1pt; letter-spacing: 0.2pt; }
.role { font-size: %(role).2fpt; font-weight: 700; margin: 0 0 1.5pt; }
.contact { font-size: 9pt; margin: 0; }
.sep { margin: 0 4pt; }
h2 { font-size: 10pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.6pt;
     border-bottom: 0.6pt solid #111; margin: 6pt 0 2.5pt; padding-bottom: 0.5pt; }
.entry { margin: 0 0 3pt; }
.row { display: flex; justify-content: space-between; align-items: baseline; gap: 10pt; }
.t { font-weight: 700; }
.s { font-style: italic; font-size: 0.97em; }
.d { white-space: nowrap; font-size: 0.97em; }
ul { margin: 1pt 0 0; padding-left: 15pt; }
li { margin: 0 0 0.8pt; padding-left: 1pt; }
.skills p { margin: 0 0 0.8pt; }
"""

SECTION_KIND = [
    (re.compile(r"experience|опыт", re.I), "experience"),
    (re.compile(r"project|проект", re.I), "projects"),
    (re.compile(r"skill|навык|технолог", re.I), "skills"),
    (re.compile(r"education|образован", re.I), "education"),
]


def e(x):
    return html.escape(x or "", quote=False)


def inline(text):
    """Экранирование + **жирный** + ссылки на email/LinkedIn/GitHub."""
    out, pos = [], 0
    for m in LINK_RE.finditer(text):
        out.append(e(text[pos:m.start()]))
        tok = m.group(0)
        href = "mailto:" + tok if m.group("email") else (tok if tok.startswith("http") else "https://" + tok)
        out.append(f'<a href="{e(href)}">{e(tok)}</a>')
        pos = m.end()
    out.append(e(text[pos:]))
    return re.sub(r"\*\*(.+?)\*\*", r'<span class="t">\1</span>', "".join(out))


def split_paren(p):
    """«Almaty, Kazakhstan, Aug 2025 – Present» → (место, даты): даты — часть с годом."""
    parts = [x.strip() for x in p.split(",")]
    for i, part in enumerate(parts):
        if DATE_HINT.search(part):
            return ", ".join(parts[:i]), ", ".join(parts[i:])
    return p.strip(), ""


def parse(md):
    lines = md.splitlines()
    cv = {"name": "", "header": [], "sections": []}
    sec = None
    entry = None
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("# ") and not cv["name"]:
            cv["name"] = re.split(r"\s+[—–-]\s+", line[2:].strip(), maxsplit=1)[0]
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            kind = next((k for rx, k in SECTION_KIND if rx.search(title)), "other")
            sec = {"title": title, "kind": kind, "items": []}
            cv["sections"].append(sec)
            entry = None
            continue
        if sec is None:
            cv["header"].append(line.strip())
            continue
        stripped = line.strip()
        if stripped.startswith(("- ", "• ", "* ")):
            text = stripped[2:].strip()
            if sec["kind"] == "skills" or entry is None:
                sec["items"].append({"type": "line", "text": text})
            else:
                entry["bullets"].append(text)
            continue
        pm = PROJECT_RE.match(stripped)
        em = ENTRY_RE.match(stripped)
        if pm and (sec["kind"] == "projects" or not em):
            entry = {"type": "project", "name": pm.group("name"), "dates": pm.group("dates").strip(),
                     "stack": (pm.group("stack") or "").strip(), "bullets": []}
        elif em:
            place, dates = split_paren(em.group("paren"))
            entry = {"type": "entry", "a": em.group("a").strip("* "), "b": em.group("b").strip("* "),
                     "place": place, "dates": dates, "bullets": []}
        else:
            sec["items"].append({"type": "line", "text": stripped})
            entry = None
            continue
        sec["items"].append(entry)
    return cv


def render(cv, font_size):
    h = cv["header"]
    head = [f"<h1>{e(cv['name'])}</h1>"]
    if h:
        head.append(f'<p class="role">{inline(h[0])}</p>')
    for line in h[1:]:
        parts = [p.strip() for p in re.split(r"\s+[·|]\s+", line) if p.strip()]
        head.append('<p class="contact">' + '<span class="sep">|</span>'.join(inline(p) for p in parts) + "</p>")
    body = []
    for sec in cv["sections"]:
        body.append(f"<h2>{e(sec['title'])}</h2>")
        if sec["kind"] == "skills":
            body.append('<div class="skills">')
        for it in sec["items"]:
            if it["type"] == "line":
                txt = it["text"]
                m = re.match(r"^([^:]{1,40}):\s*(.+)$", txt)
                if sec["kind"] == "skills" and m:
                    body.append(f'<p><span class="t">{e(m.group(1))}:</span> {inline(m.group(2))}</p>')
                else:
                    body.append(f"<p>{inline(txt)}</p>")
                continue
            body.append('<div class="entry">')
            if it["type"] == "project":
                stack = f' | <span class="s">{e(it["stack"])}</span>' if it["stack"] else ""
                body.append(f'<div class="row"><span><span class="t">{e(it["name"])}</span>{stack}</span>'
                            f'<span class="d">{e(it["dates"])}</span></div>')
            else:
                # Experience: «Должность — Компания»; Education: «Университет — Степень».
                top_l, sub_l = it["a"], it["b"]
                if sec["kind"] == "education":
                    body.append(f'<div class="row"><span class="t">{e(top_l)}</span><span class="d">{e(it["place"])}</span></div>'
                                f'<div class="row"><span class="s">{e(sub_l)}</span><span class="s">{e(it["dates"])}</span></div>')
                else:
                    body.append(f'<div class="row"><span class="t">{e(top_l)}</span><span class="d">{e(it["dates"])}</span></div>'
                                f'<div class="row"><span class="s">{e(sub_l)}</span><span class="s">{e(it["place"])}</span></div>')
            if it["bullets"]:
                body.append("<ul>" + "".join(f"<li>{inline(b)}</li>" for b in it["bullets"]) + "</ul>")
            body.append("</div>")
        if sec["kind"] == "skills":
            body.append("</div>")
    css = CSS % {"fs": font_size, "role": font_size + 1.3}
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(cv["name"])} — CV</title>'
            f"<style>{css}</style></head><body><header>{''.join(head)}</header>{''.join(body)}</body></html>")


def find_browser(explicit=None):
    for b in ([explicit] if explicit else []) + BROWSERS:
        if not b:
            continue
        if os.path.isabs(b) and os.path.exists(b):
            return b
        p = shutil.which(b)
        if p:
            return p
    return None


def print_pdf(browser, html_path, pdf_path):
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
           f"--print-to-pdf={pdf_path}", "file://" + os.path.abspath(html_path)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
        # старые версии Chrome не знают --headless=new
        cmd[1] = "--headless"
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0


def page_count(pdf_path):
    data = open(pdf_path, "rb").read()
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def ats_text(pdf_path):
    if not shutil.which("pdftotext"):
        return None
    r = subprocess.run(["pdftotext", "-layout", pdf_path, "-"], capture_output=True, text=True)
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="~/.kz-job-hunter/resume.md")
    ap.add_argument("--out", default="~/Downloads/CV.pdf")
    ap.add_argument("--html", help="куда сохранить HTML (по умолчанию рядом с PDF)")
    ap.add_argument("--browser", help="путь к Chrome/Chromium, если не находится сам")
    ap.add_argument("--font-size", type=float, default=9.7)
    ap.add_argument("--min-font-size", type=float, default=8.8, help="до какого кегля ужимать, чтобы влезть в 1 страницу")
    ap.add_argument("--pages", type=int, default=1, help="целевое число страниц")
    a = ap.parse_args()

    src = os.path.expanduser(a.inp)
    out = os.path.expanduser(a.out)
    cv = parse(open(src, encoding="utf-8").read())
    if not cv["name"] or not cv["sections"]:
        sys.exit("Не удалось разобрать резюме: нужна строка «# Имя» и разделы «## …». Формат — в шапке скрипта.")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    html_path = os.path.expanduser(a.html) if a.html else os.path.splitext(out)[0] + ".html"

    browser = find_browser(a.browser)
    fs = a.font_size
    report = {"pdf": None, "html": html_path, "pages": None, "font_size": None, "ats_ok": None, "warnings": []}
    while True:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render(cv, fs))
        if not browser:
            report["warnings"].append("браузер не найден — откройте HTML и сохраните как PDF через печать")
            break
        with tempfile.TemporaryDirectory() as td:
            tmp_pdf = os.path.join(td, "cv.pdf")
            if not print_pdf(browser, html_path, tmp_pdf):
                report["warnings"].append("браузер не смог напечатать PDF")
                break
            pages = page_count(tmp_pdf)
            if pages > a.pages and round(fs - 0.3, 2) >= a.min_font_size:
                fs = round(fs - 0.3, 2)
                continue
            shutil.copyfile(tmp_pdf, out)
        report.update(pdf=out, pages=pages, font_size=fs)
        if pages > a.pages:
            report["warnings"].append(f"{pages} стр. даже при {fs}pt — сократите текст (старые/слабые пункты)")
        break

    if report["pdf"]:
        text = ats_text(out)
        if text is None:
            report["warnings"].append("pdftotext не установлен — ATS-проверка текста пропущена")
        else:
            flat = re.sub(r"\s+", " ", text)
            missing = [s["title"] for s in cv["sections"] if s["title"].upper() not in flat.upper()]
            ok = cv["name"].split()[0] in flat and not missing
            report["ats_ok"] = ok
            if missing:
                report["warnings"].append("ATS не видит заголовки: " + ", ".join(missing))
    if report["html"] and report["pdf"] and not a.html:
        os.remove(html_path)
        report["html"] = None
    import json
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
