#!/usr/bin/env python3
"""
kz_jobs.py — сборщик вакансий для Казахстана (без внешних зависимостей, только stdlib).

Источники:
  hh        — hh.kz / hh.ru / hh.uz / rabota.by (HH-Lux-InitialState; логин не нужен)
  enbek     — enbek.kz (Электронная биржа труда)
  tg        — публичные Telegram-каналы через t.me/s/<канал>
  habr, getmatch, geekjob — IT-площадки СНГ (открытые JSON-эндпоинты)
  remoteok, himalayas, wwr, workingnomads, remotive, jobicy — международная удалёнка (публичные API/RSS)

Команды:
  python3 kz_jobs.py search  --profile profile.json --out run.json [--sources hh,enbek,tg] [--details]
  python3 kz_jobs.py report  --in run.json --out report.md
  python3 kz_jobs.py refilter --in run.json --profile profile.json   # перефильтровать без запросов
  python3 kz_jobs.py mark-seen --in run.json --profile profile.json   # записать найденное в историю

Скрипт ничего не отправляет работодателям — только читает публичные страницы.
"""
import argparse
import html
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
ALMATY_TZ = timezone(timedelta(hours=5))

# Курсы по умолчанию (тенге за единицу). Переопределяются в profile.json → "rates".
DEFAULT_RATES = {"KZT": 1, "USD": 510, "EUR": 590, "RUR": 6.3, "RUB": 6.3,
                 "UZS": 0.04, "KGS": 5.8, "BYN": 155}
# Грубый коэффициент gross → «на руки» для РК (ОПВ 10% + ВОСМС 2% + ИПН ~10%).
DEFAULT_NET_RATIO = 0.80

HH_WORK_FORMAT_RU = {"REMOTE": "удалённо", "HYBRID": "гибрид", "ON_SITE": "офис",
                     "FIELD_WORK": "разъездной"}
EXPERIENCE_RU = {"noExperience": "без опыта", "between1And3": "1–3 года",
                 "between3And6": "3–6 лет", "moreThan6": "6+ лет"}
CEFR = ["a1", "a2", "b1", "b2", "c1", "c2", "l1"]  # l1 = родной

RU_ONLY_RE = re.compile(
    r"удал[её]нн?о\s+по\s+(росси|рф)|на\s+территории\s+(рф|россии)|только\s+в\s+(рф|россии)|"
    r"резидентств[а-яё]*\s+рф|граждан[а-яё]*\s+рф|налогов[а-яё]*\s+резидент[а-яё]*\s+рф", re.I)
KAZAKH_RE = re.compile(r"казахск[а-яё]*\s+язык|қазақ\s+тіл|знание\s+казахского|kazakh\s+language", re.I)
REMOTE_WORD_RE = re.compile(r"удал[её]н|remote|из\s+любого\s+города|из\s+любой\s+точки", re.I)
GEO_OK_RE = re.compile(r"казахстан|kazakhstan|\bкз\b|\bkz\b|снг|\bcis\b|центральн[а-я]*\s+ази|central\s+asia|"
                       r"любой\s+стран|любой\s+точки\s+мира|из\s+любой\s+точки(?!\s+росси)|по\s+миру|весь\s+мир|"
                       r"worldwide|anywhere|any\s+country|global", re.I)
GEO_RU_RE = re.compile(r"\bрф\b|росси[ияю]|\bрб\b|беларус", re.I)
GEO_OTHER_RE = re.compile(r"latam|latin\s+america|\beurope|\beu\b|европ|\busa?\b|united\s+states|\buk\b|canada|"
                          r"португал|portugal|испани|spain|серби|serbia|грузи|georgia|кипр|cyprus|польш|poland|"
                          r"израил|israel|\bcet\b|\bcest\b|\best\b|\bpst\b", re.I)


def geo_check(text):
    """Смотрим предложения про удалёнку: ('drop'|'flag'|None, пояснение)."""
    ru = other = None
    for sent in re.split(r"[.\n;!?•·]+", text or ""):
        if not REMOTE_WORD_RE.search(sent):
            continue
        if GEO_OK_RE.search(sent):
            return None, ""
        if GEO_RU_RE.search(sent) and not ru:
            ru = sent.strip()[:80]
        elif GEO_OTHER_RE.search(sent) and not other:
            other = sent.strip()[:80]
    if ru:
        return "drop", f"удалёнка только РФ/РБ: «{ru}»"
    if other:
        return "flag", f"удалёнка с ограничением по стране: «{other}»"
    return None, ""


AD_RE = re.compile(r"\bкурс[аеуы]?\b|вебинар|урок\s+пройд|интенсив|канал\s+с\s+вакансиями|подписывайтесь|скидк", re.I)
TEST_TASK_RE = re.compile(r"тестов[а-яё]*\s+задани|test\s*(task|assignment)", re.I)
CITIZEN_KZ_RE = re.compile(r"только\s+граждан[а-яё]*\s+(рк|казахстана)|гражданство\s+(рк|казахстана)\s+обязательн", re.I)


# ───────────────────────── HTTP ─────────────────────────

def fetch(url, timeout=25, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept-Language": "ru-RU,ru;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 — одна ошибка не должна ронять прогон
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def polite_pause():
    time.sleep(random.uniform(1.0, 2.2))


def strip_html(s):
    s = re.sub(r"<br\s*/?>|</p>|</li>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


# ───────────────────────── hh.kz ─────────────────────────

def hh_state(page_html):
    m = re.search(r'<template[^>]*id="HH-Lux-InitialState"[^>]*>(.*?)</template>', page_html, re.S)
    if not m:
        raise RuntimeError("HH-Lux-InitialState не найден (капча или смена вёрстки)")
    return json.loads(html.unescape(m.group(1)))


def _hh_list(v, key, inner):
    """hh отдаёт списки как [{"inner": [...]}] — разворачиваем."""
    out = []
    for item in v.get(key) or []:
        if isinstance(item, dict):
            out += item.get(inner) or []
        else:
            out.append(item)
    return out


def hh_sites(profile):
    """Список сайтов hh: [{"domain", "areas", "work_formats"}]. Обратная совместимость с hh_areas."""
    if profile.get("hh_sites"):
        return profile["hh_sites"]
    return [{"domain": "hh.kz", "areas": profile.get("hh_areas", [40]),
             "work_formats": profile.get("work_formats", [])}]


def hh_search(profile, log):
    p = profile
    days = int(p.get("max_age_days", 3))
    results = []
    for site in hh_sites(p):
        dom = site["domain"]
        for kw in p["keywords"]:
            params = [("text", kw), ("order_by", "publication_time"),
                      ("search_period", str(max(1, days))), ("items_on_page", "50")]
            if p.get("title_only", True):
                params.append(("search_field", "name"))
            for a in site.get("areas", []):
                params.append(("area", str(a)))
            for wf in site.get("work_formats", []):
                params.append(("work_format", wf))
            for page in range(int(p.get("hh_max_pages", 3))):
                url = f"https://{dom}/search/vacancy?" + urllib.parse.urlencode(params + [("page", str(page))])
                try:
                    st = hh_state(fetch(url))
                except Exception as e:  # noqa: BLE001
                    log.append(f"{dom}: «{kw}» стр.{page}: {e}")
                    break
                sr = st.get("vacancySearchResult", {})
                vacs = sr.get("vacancies", [])
                if not sr.get("totalResults"):
                    vacs = []  # при 0 результатов hh подмешивает «похожие» — не берём их
                for v in vacs:
                    results.append(_hh_item(v, dom, kw))
                log.append(f"{dom}: «{kw}» стр.{page}: {len(vacs)} шт. (всего по запросу {sr.get('totalResults')})")
                polite_pause()
                pages = (sr.get("paging") or {}).get("pages") or []
                if not vacs or page + 1 >= len(pages):
                    break
    return results


def _hh_item(v, dom, kw):
    c = v.get("company") or {}
    langs = _hh_list(v, "languages", "language")
    return {
        "source": dom,
        "id": f"hh:{v['vacancyId']}",  # id вакансий у hh общие для всех доменов
        "url": f"https://{dom}/vacancy/{v['vacancyId']}",
        "title": v.get("name", ""),
        "company": c.get("visibleName") or c.get("name") or "",
        "city": (v.get("area") or {}).get("name", ""),
        "salary": v.get("compensation"),
        "published": (v.get("publicationTime") or {}).get("$"),
        "work_formats": _hh_list(v, "workFormats", "workFormatsElement"),
        "experience": v.get("workExperience"),
        "languages": [{"code": l.get("isoCode"), "level": l.get("degree")} for l in langs],
        "has_test": bool(v.get("userTestPresent")),
        "letter_required": bool(v.get("@responseLetterRequired")),
        "responses": v.get("totalResponsesCount"),
        "snippet": "",
        "matched_keyword": kw,
    }


def hh_details(vac, log):
    vid = vac["id"].split(":", 1)[1]
    try:
        st = hh_state(fetch(vac["url"]))
        v = st["vacancyView"]["vacancyFull"]["vacancy"]
    except Exception as e:  # noqa: BLE001
        log.append(f"{vac['source']} детали {vid}: {e}")
        return vac
    vac["description"] = strip_html(v.get("description"))
    vac["key_skills"] = v.get("keySkills") or []
    if v.get("languages"):
        vac["languages"] = [{"code": l.get("isoCode"), "level": l.get("degree")} for l in v["languages"]]
    if v.get("closedForApplicants"):
        vac["closed"] = True
    return vac


# ───────────────────────── enbek.kz ─────────────────────────

ENBEK_PRICE_RE = re.compile(r'<div class="price">(.*?)</div>', re.S)


def enbek_search(profile, log):
    days = int(profile.get("max_age_days", 3))
    cutoff = datetime.now(ALMATY_TZ).date() - timedelta(days=days)
    out = []
    for kw in profile["keywords"]:
        url = "https://www.enbek.kz/ru/search/vacancy?" + urllib.parse.urlencode({"prof": kw})
        try:
            page = fetch(url)
        except Exception as e:  # noqa: BLE001
            log.append(f"enbek.kz: «{kw}»: {e}")
            continue
        cards = re.split(r'<div class="item-list', page)[1:]
        n = 0
        for card in cards:
            href = re.search(r'href="(/ru/vacancy/[^"]+)"', card)
            if not href:
                continue
            title = re.search(r'class="stretched"[^>]*>(.*?)</a>', card, re.S)
            sub = re.search(r'<div class="subtitle">(.*?)</div>', card, re.S)
            comp = re.search(r'<span class="company-name">(.*?)</span>', card, re.S)
            loc = re.search(r'<li class="location[^"]*">(.*?)</li>', card, re.S)
            price = ENBEK_PRICE_RE.search(card)
            date = re.search(r"Опубликовано\s+(\d{2}\.\d{2}\.\d{4})", card)
            pub = None
            if date:
                d = datetime.strptime(date.group(1), "%d.%m.%Y").date()
                if d < cutoff:
                    continue
                pub = d.isoformat()
            sal = None
            if price:
                nums = [int(x.replace(" ", "").replace("\xa0", "")) for x in
                        re.findall(r"\d[\d \xa0]*", strip_html(price.group(1)))]
                if nums:
                    sal = {"from": nums[0], "to": nums[1] if len(nums) > 1 else None,
                           "currencyCode": "KZT", "gross": True}
            t = strip_html(title.group(1)) if title else ""
            s = strip_html(sub.group(1)) if sub else ""
            out.append({
                "source": "enbek.kz",
                "id": "enbek:" + href.group(1).rsplit("~", 1)[-1],
                "url": "https://www.enbek.kz" + href.group(1),
                "title": f"{s} ({t})" if s and t and s != t else (s or t),
                "company": strip_html(comp.group(1)) if comp else "",
                "city": strip_html(loc.group(1)) if loc else "",
                "salary": sal, "published": pub, "work_formats": [],
                "languages": [], "has_test": False, "snippet": "",
                "matched_keyword": kw,
            })
            n += 1
        log.append(f"enbek.kz: «{kw}»: {n} шт.")
        polite_pause()
    return out


# ───────────────────────── Telegram (t.me/s) ─────────────────────────

def tg_search(profile, log):
    days = int(profile.get("tg_max_age_days", max(7, int(profile.get("max_age_days", 3)))))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kw_re = re.compile("|".join(re.escape(k) for k in profile["keywords"]), re.I)
    out, tg_seen_text = [], set()
    for ch in profile.get("tg_channels", []):
        ch = ch.lstrip("@")
        try:
            page = fetch(f"https://t.me/s/{ch}")
        except Exception as e:  # noqa: BLE001
            log.append(f"t.me/{ch}: {e}")
            continue
        posts = re.split(r'<div class="tgme_widget_message_wrap', page)[1:]
        last_dt, n = None, 0
        for p in posts:
            post = re.search(r'data-post="([^"]+)"', p)
            dt = re.search(r'<time[^>]*datetime="([^"]+)"', p)
            txt = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', p, re.S)
            if not (post and dt and txt):
                continue
            when = datetime.fromisoformat(dt.group(1))
            last_dt = max(last_dt or when, when)
            text = strip_html(txt.group(1))
            if when < cutoff or not kw_re.search(text):
                continue
            first = tg_title(text, profile)
            fp = re.sub(r"\W+", "", text.lower())[:200]
            if fp in tg_seen_text:  # один и тот же пост, разосланный по нескольким каналам
                continue
            tg_seen_text.add(fp)
            out.append({
                "source": f"t.me/{ch}",
                "id": f"tg:{post.group(1)}",
                "url": f"https://t.me/{post.group(1)}",
                "title": first, "company": "", "city": "",
                "salary": None, "published": when.isoformat(), "work_formats": [],
                "languages": [], "has_test": False,
                "description": text, "snippet": text[:400],
                "matched_keyword": kw_re.search(text).group(0),
            })
            n += 1
        age = f", последний пост {last_dt.date()}" if last_dt else ", постов не видно"
        log.append(f"t.me/{ch}: {n} подходящих{age}")
        polite_pause()
    return out


JOB_WORD_RE = re.compile(r"developer|engineer|разработчик|инженер|аналитик|analyst|manager|менеджер|"
                         r"lead|лид|designer|дизайнер|специалист|specialist|architect|архитектор|"
                         r"тестировщик|qa\b|devops|scientist|head of|руководител|вакансия|position|должность", re.I)


def tg_title(text, profile):
    """Строка поста, больше всего похожая на название должности."""
    tre = profile.get("title_must_match")
    lines = []
    for l in text.split("\n"):
        l = re.sub(r"#\w+", "", l)
        l = re.sub(r"^[^\wА-Яа-яЁё]+", "", l).strip(" ,.:;|-–—")
        if len(re.sub(r"\W", "", l)) >= 4:
            lines.append(l)
    head = lines[:8]
    for test in ([lambda l: re.search(tre, l, re.I) and JOB_WORD_RE.search(l)] if tre else []) + \
                [lambda l: JOB_WORD_RE.search(l), lambda l: True]:
        for l in head:
            if test(l):
                l = re.sub(r"^(вакансия|должность|position|role)\s*[:\-–—]?\s*", "", l, flags=re.I)
                return l[:140]
    return text[:140]


# ───────────────────────── общие помощники ─────────────────────────

def item(source, id_, url, title, kw, **kw2):
    base = {"source": source, "id": id_, "url": url, "title": title or "", "company": "",
            "city": "", "salary": None, "published": None, "work_formats": [], "languages": [],
            "has_test": False, "snippet": "", "matched_keyword": kw, "region": ""}
    base.update(kw2)
    return base


def kw_regex(profile):
    return re.compile("|".join(re.escape(k) for k in profile["keywords"]), re.I)


def cutoff_utc(profile):
    return datetime.now(timezone.utc) - timedelta(days=int(profile.get("max_age_days", 3)))


def parse_dt(x):
    try:
        if isinstance(x, (int, float)) or (isinstance(x, str) and x.isdigit()):
            return datetime.fromtimestamp(int(x), timezone.utc)
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(x)
        except Exception:  # noqa: BLE001
            return None


def fresh(dt, cutoff):
    return dt is None or dt >= cutoff


def fetch_json(url):
    return json.loads(fetch(url))


# ───────────────────────── СНГ: Habr Career, getmatch, GeekJob ─────────────────────────

def habr_search(profile, log):
    cut, out = cutoff_utc(profile), []
    for kw in profile["keywords"]:
        params = [("q", kw), ("type", "all"), ("sort", "date")]
        if profile.get("habr_remote_only", True):
            params.append(("remote", "true"))
        for loc in profile.get("habr_locations", []):
            params.append(("locations[]", loc))
        try:
            d = fetch_json("https://career.habr.com/api/frontend/vacancies?" + urllib.parse.urlencode(params))
        except Exception as e:  # noqa: BLE001
            log.append(f"career.habr.com: «{kw}»: {e}")
            continue
        n = 0
        for v in d.get("list", []):
            dt = parse_dt((v.get("publishedDate") or {}).get("date"))
            if not fresh(dt, cut):
                continue
            sal = v.get("salary") or {}
            cur = (sal.get("currency") or "").upper().replace("RUR", "RUB") or None
            out.append(item(
                "career.habr.com", f"habr:{v['id']}", "https://career.habr.com" + v["href"], v.get("title"), kw,
                company=(v.get("company") or {}).get("title", ""),
                city=", ".join(l["title"] for l in v.get("locations") or []),
                salary={"from": sal.get("from"), "to": sal.get("to"), "currencyCode": cur} if (sal.get("from") or sal.get("to")) else None,
                published=dt.isoformat() if dt else None,
                work_formats=["REMOTE"] if v.get("remoteWork") else [],
                key_skills=[x["title"] for x in v.get("skills") or []]))
            n += 1
        log.append(f"career.habr.com: «{kw}»: {n} шт.")
        polite_pause()
    return out


GM_FORMAT = {"remote": "REMOTE", "office": "ON_SITE", "hybrid": "HYBRID"}


def getmatch_search(profile, log):
    """getmatch не фильтрует по тексту на сервере — берём свежую ленту и фильтруем сами."""
    cut, kre, out = cutoff_utc(profile), kw_regex(profile), []
    for offset in range(0, int(profile.get("getmatch_max", 300)), 100):
        try:
            d = fetch_json(f"https://getmatch.ru/api/offers?limit=100&offset={offset}")
        except Exception as e:  # noqa: BLE001
            log.append(f"getmatch.ru: {e}")
            break
        offers = d.get("offers", [])
        stop = False
        for o in offers:
            dt = parse_dt(o.get("published_at"))
            if dt and dt < cut:
                stop = True
                continue
            skills = [x.get("name", "") for x in o.get("skills_objects") or []]
            hay = f"{o.get('position','')} {' '.join(skills)}"
            m = kre.search(hay)
            if not m or not o.get("is_active", True):
                continue
            locs = o.get("location_items") or []
            sf, st = o.get("salary_display_from"), o.get("salary_display_to")
            out.append(item(
                "getmatch.ru", f"getmatch:{o['id']}", "https://getmatch.ru" + o["url"], o.get("position"), m.group(0),
                company=(o.get("company") or {}).get("name") or "",
                city=", ".join(sorted({l.get("label", "") for l in locs})),
                work_formats=sorted({GM_FORMAT.get(l.get("format"), "") for l in locs} - {""}),
                salary={"from": sf, "to": st, "currencyCode": (o.get("salary_currency") or "RUB").upper(),
                        "gross": o.get("salary_taxes") == "gross"} if (sf or st) else None,
                published=dt.isoformat() if dt else None, key_skills=skills,
                snippet=strip_html(o.get("offer_description") or "")[:400]))
        polite_pause()
        if stop or len(offers) < 100:
            break
    log.append(f"getmatch.ru: {len(out)} шт.")
    return out


def geekjob_search(profile, log):
    days, out = int(profile.get("max_age_days", 3)), []
    min_sort = int((datetime.now(ALMATY_TZ) - timedelta(days=days)).strftime("%Y%m%d"))
    for kw in profile["keywords"]:
        try:
            d = fetch_json("https://geekjob.ru/json/find/vacancy?" + urllib.parse.urlencode({"qs": kw}))
        except Exception as e:  # noqa: BLE001
            log.append(f"geekjob.ru: «{kw}»: {e}")
            continue
        n = 0
        for v in d.get("data", []):
            if int(str(v.get("sortOrder") or 0)[:8] or 0) < min_sort:
                continue
            jf = v.get("jobFormat") or {}
            fmts = (["REMOTE"] if jf.get("remote") else []) + (["ON_SITE"] if jf.get("inhouse") else [])
            out.append(item(
                "geekjob.ru", f"geekjob:{v['id']}", f"https://geekjob.ru/vacancy/{v['id']}", v.get("position"), kw,
                company=(v.get("company") or {}).get("name", ""),
                city=", ".join(x for x in [v.get("country"), v.get("city")] if x),
                work_formats=fmts, snippet=f"Зарплата: {v['salary']}" if v.get("salary") else ""))
            n += 1
        log.append(f"geekjob.ru: «{kw}»: {n} шт.")
        polite_pause()
    return out


# ───────────────────────── международная удалёнка ─────────────────────────

def _usd(a, b, period="year"):
    a, b = int(a or 0) or None, int(b or 0) or None
    if not (a or b):
        return None
    return {"from": a, "to": b, "currencyCode": "USD", "mode": "YEAR" if period.startswith("year") or period == "annual" else "MONTH"}


def remoteok_search(profile, log):
    cut, kre, out = cutoff_utc(profile), kw_regex(profile), []
    try:
        data = fetch_json("https://remoteok.com/api")[1:]
    except Exception as e:  # noqa: BLE001
        log.append(f"remoteok.com: {e}")
        return out
    for j in data:
        dt = parse_dt(j.get("date"))
        m = kre.search(f"{j.get('position','')} {' '.join(j.get('tags') or [])}")
        if not m or not fresh(dt, cut):
            continue
        out.append(item("remoteok.com", f"rok:{j['id']}", j.get("url"), j.get("position"), m.group(0),
                        company=j.get("company", ""), region=j.get("location") or "",
                        work_formats=["REMOTE"], published=dt.isoformat() if dt else None,
                        salary=_usd(j.get("salary_min"), j.get("salary_max")),
                        key_skills=j.get("tags") or [],
                        snippet=strip_html(j.get("description") or "")[:400]))
    log.append(f"remoteok.com: {len(out)} шт. (источник: Remote OK)")
    return out


def himalayas_search(profile, log):
    cut, out = cutoff_utc(profile), []
    for kw in profile["keywords"]:
        try:
            d = fetch_json("https://himalayas.app/jobs/api/search?" + urllib.parse.urlencode({"q": kw}))
        except Exception as e:  # noqa: BLE001
            log.append(f"himalayas.app: «{kw}»: {e}")
            continue
        n = 0
        for j in d.get("jobs", []):
            dt = parse_dt(j.get("pubDate"))
            if not fresh(dt, cut):
                continue
            mn, mx = j.get("minSalary"), j.get("maxSalary")
            out.append(item("himalayas.app", "him:" + j["guid"], j.get("applicationLink") or j["guid"], j.get("title"), kw,
                            company=j.get("companyName", ""), region=", ".join(j.get("locationRestrictions") or []),
                            work_formats=["REMOTE"], published=dt.isoformat() if dt else None,
                            salary={"from": mn, "to": mx, "currencyCode": j.get("currency") or "USD",
                                    "mode": "YEAR" if (j.get("salaryPeriod") or "annual") == "annual" else "MONTH"} if (mn or mx) else None,
                            snippet=strip_html(j.get("excerpt") or "")[:400]))
            n += 1
        log.append(f"himalayas.app: «{kw}»: {n} шт.")
        polite_pause()
    return out


def wwr_search(profile, log):
    cut, kre, out = cutoff_utc(profile), kw_regex(profile), []
    try:
        rss = fetch("https://weworkremotely.com/remote-jobs.rss")
    except Exception as e:  # noqa: BLE001
        log.append(f"weworkremotely.com: {e}")
        return out
    for it in re.findall(r"<item>(.*?)</item>", rss, re.S):
        g = lambda t: html.unescape((re.search(rf"<{t}>(.*?)</{t}>", it, re.S) or [None, ""])[1]).strip()  # noqa: E731
        full_title, link = g("title"), g("link")
        dt = parse_dt(g("pubDate"))
        m = kre.search(f"{full_title} {g('skills')}")
        if not m or not fresh(dt, cut):
            continue
        comp, _, title = full_title.partition(": ")
        out.append(item("weworkremotely.com", "wwr:" + link.rsplit("/", 1)[-1], link, title or full_title, m.group(0),
                        company=comp if title else "", region=g("region"), work_formats=["REMOTE"],
                        published=dt.isoformat() if dt else None,
                        snippet=strip_html(g("description"))[:400]))
    log.append(f"weworkremotely.com: {len(out)} шт.")
    return out


def workingnomads_search(profile, log):
    cut, kre, out = cutoff_utc(profile), kw_regex(profile), []
    try:
        data = fetch_json("https://www.workingnomads.com/api/exposed_jobs/")
    except Exception as e:  # noqa: BLE001
        log.append(f"workingnomads.com: {e}")
        return out
    for j in data:
        dt = parse_dt(j.get("pub_date"))
        m = kre.search(f"{j.get('title','')} {j.get('tags','')}")
        if not m or not fresh(dt, cut):
            continue
        out.append(item("workingnomads.com", "wn:" + j["url"].rstrip("/").rsplit("/", 1)[-1], j["url"], j.get("title"), m.group(0),
                        company=j.get("company_name", ""), region=j.get("location") or "",
                        work_formats=["REMOTE"], published=dt.isoformat() if dt else None,
                        snippet=strip_html(j.get("description") or "")[:400]))
    log.append(f"workingnomads.com: {len(out)} шт.")
    return out


def remotive_search(profile, log):
    cut, out = cutoff_utc(profile), []
    for kw in profile["keywords"]:
        try:
            d = fetch_json("https://remotive.com/api/remote-jobs?" + urllib.parse.urlencode({"search": kw, "limit": 50}))
        except Exception as e:  # noqa: BLE001
            log.append(f"remotive.com: «{kw}»: {e}")
            continue
        n = 0
        for j in d.get("jobs", []):
            dt = parse_dt(j.get("publication_date"))
            if not fresh(dt, cut):
                continue
            out.append(item("remotive.com", f"remotive:{j['id']}", j["url"], j.get("title"), kw,
                            company=j.get("company_name", ""), region=j.get("candidate_required_location") or "",
                            work_formats=["REMOTE"], published=dt.isoformat() if dt else None,
                            snippet=(f"Зарплата: {j['salary']}. " if j.get("salary") else "") + strip_html(j.get("description") or "")[:400]))
            n += 1
        log.append(f"remotive.com: «{kw}»: {n} шт.")
        polite_pause()
    return out


def jobicy_search(profile, log):
    cut, out = cutoff_utc(profile), []
    for kw in profile["keywords"]:
        try:
            d = fetch_json("https://jobicy.com/api/v2/remote-jobs?" + urllib.parse.urlencode({"count": 50, "tag": kw}))
        except Exception as e:  # noqa: BLE001
            log.append(f"jobicy.com: «{kw}»: {e}")
            continue
        n = 0
        for j in d.get("jobs", []) or []:
            dt = parse_dt(j.get("pubDate"))
            if not fresh(dt, cut) or not re.search(re.escape(kw), f"{j.get('jobTitle','')} {j.get('jobIndustry','')}", re.I):
                continue
            out.append(item("jobicy.com", f"jobicy:{j['id']}", j["url"], j.get("jobTitle"), kw,
                            company=j.get("companyName", ""), region=j.get("jobGeo") or "",
                            work_formats=["REMOTE"], published=dt.isoformat() if dt else None,
                            salary=_usd(j.get("salaryMin") or j.get("annualSalaryMin"), j.get("salaryMax") or j.get("annualSalaryMax"),
                                        j.get("salaryPeriod") or "yearly") if (j.get("salaryMin") or j.get("annualSalaryMin")) else None,
                            snippet=strip_html(j.get("jobExcerpt") or "")[:400]))
            n += 1
        log.append(f"jobicy.com: «{kw}»: {n} шт.")
        polite_pause()
    return out


SOURCES = {
    "hh": hh_search, "enbek": lambda p, l: enbek_search(p, l), "tg": lambda p, l: tg_search(p, l),
    "habr": habr_search, "getmatch": getmatch_search, "geekjob": geekjob_search,
    "remoteok": remoteok_search, "himalayas": himalayas_search, "wwr": wwr_search,
    "workingnomads": workingnomads_search, "remotive": remotive_search, "jobicy": jobicy_search,
}
DEFAULT_SOURCES = "hh,enbek,tg,habr,getmatch,geekjob,remoteok,himalayas,wwr,workingnomads,remotive,jobicy"
DEFAULT_REMOTE_REGIONS = (r"worldwide|anywhere|global|^remote$|emea|asia|apac|cis|снг|kazakhstan|казахстан|"
                          r"central asia|eurasia|all countries|international")


# ───────────────────────── фильтры ─────────────────────────

def salary_kzt_net(sal, profile):
    """Верхняя граница вилки в тенге «на руки» (или None, если зарплата не указана)."""
    if not sal or not (sal.get("from") or sal.get("to")):
        return None
    rates = {**DEFAULT_RATES, **profile.get("rates", {})}
    val = sal.get("to") or sal.get("from")
    cur = (sal.get("currencyCode") or "KZT").upper()
    kzt = val * rates.get(cur, 1)
    mode = (sal.get("mode") or "MONTH")
    if isinstance(mode, dict):
        mode = mode.get("$", "MONTH")
    if mode == "HOUR":
        kzt *= 168
    elif mode == "DAY":
        kzt *= 21
    elif mode == "YEAR":
        kzt /= 12
    if sal.get("gross"):
        kzt *= profile.get("net_ratio", DEFAULT_NET_RATIO)
    return round(kzt)


def fmt_salary(sal):
    if not sal or not (sal.get("from") or sal.get("to")):
        return "не указана"
    cur = {"KZT": "₸", "USD": "$", "EUR": "€", "RUR": "₽", "RUB": "₽"}.get(
        (sal.get("currencyCode") or "KZT").upper(), sal.get("currencyCode"))
    f = lambda x: f"{x:,}".replace(",", " ")  # noqa: E731
    a, b = sal.get("from"), sal.get("to")
    rng = f"{f(a)}–{f(b)}" if a and b else (f"от {f(a)}" if a else f"до {f(b)}")
    gross = " (до вычетов)" if sal.get("gross") else " (на руки)" if sal.get("gross") is False else ""
    return f"{rng} {cur}{gross}"


def classify(v, profile, seen):
    """Возвращает ('keep'|'flag'|'drop', [причины])."""
    title = v.get("title", "")
    full = f"{title}\n{v.get('description') or v.get('snippet') or ''}"
    reasons_drop, flags = [], []

    if v["id"] in seen:
        return "drop", ["уже видели"]
    if v.get("closed"):
        return "drop", ["закрыта для откликов"]
    if v["source"].startswith("t.me") and AD_RE.search(full[:400]):
        return "drop", ["реклама / не вакансия"]

    tre = profile.get("title_must_match")
    if tre and not re.search(tre, title, re.I):
        reasons_drop.append("название не по профилю")
    for pat in profile.get("exclude_title", []):
        if re.search(pat, title, re.I):
            reasons_drop.append(f"исключено по названию: {pat}")
    # Все исключения проверяем по ПОЛНОМУ тексту, а не только по названию.
    for pat in profile.get("exclude_text", []):
        if re.search(pat, full, re.I):
            reasons_drop.append(f"исключено по тексту: {pat}")
    # Обязательный стек: если есть описание или ключевые навыки, в них должно встречаться хоть что-то из профиля.
    req = profile.get("require_in_text")
    if req:
        skills_txt = " ".join(v.get("key_skills") or [])
        has_body = bool(v.get("description") or skills_txt)
        if has_body and not re.search(req, f"{full}\n{skills_txt}", re.I):
            reasons_drop.append("стек не тот (нет " + req + ")")
        elif skills_txt and not re.search(req, f"{title} {skills_txt}", re.I) and \
                re.search(r"node|typescript|java\b|spring|php|laravel|golang|\bgo\b|c#|\.net|kotlin", skills_txt, re.I):
            reasons_drop.append("стек не тот (по ключевым навыкам)")
    for comp in profile.get("exclude_companies", []):
        if comp.lower() in (v.get("company") or "").lower():
            reasons_drop.append(f"компания в стоп-листе: {comp}")

    geo_kind, geo_why = geo_check(full) if profile.get("geo_check", True) else (None, "")
    if profile.get("exclude_ru_only_remote", True) and (RU_ONLY_RE.search(full) or geo_kind == "drop"):
        reasons_drop.append(geo_why or "удалёнка только для РФ")

    region = (v.get("region") or "").strip()
    allowed = profile.get("remote_allowed_regions", DEFAULT_REMOTE_REGIONS)
    if region and allowed and not re.search(allowed, region, re.I):
        reasons_drop.append(f"регион найма: {region[:60]}")

    wf = profile.get("work_formats")
    if wf and v.get("work_formats") and not set(wf) & set(v["work_formats"]):
        reasons_drop.append("формат работы не подходит")
    elif wf == ["REMOTE"] and not v.get("work_formats") and (v.get("description") or v.get("snippet")) \
            and not REMOTE_WORD_RE.search(full):
        reasons_drop.append("в тексте нет удалёнки")

    floor = profile.get("salary_min_kzt_net")
    net = salary_kzt_net(v.get("salary"), profile)
    v["salary_kzt_net"] = net
    if floor and net is not None and net < floor:
        reasons_drop.append(f"зарплата ниже порога (~{net:,} ₸ на руки)".replace(",", " "))

    if reasons_drop:
        return "drop", reasons_drop

    # Флаги — не скрываем, а показываем отдельно.
    langs = {l.get("code"): (l.get("level") or "").lower() for l in v.get("languages") or []}
    knows_kazakh = profile.get("kazakh_level", "none").lower()
    if ("kaz" in langs or KAZAKH_RE.search(full)) and knows_kazakh in ("none", "a1", "a2", ""):
        flags.append("нужен казахский язык")
    my_en = profile.get("english_level", "b1").lower()
    need_en = langs.get("eng")
    if need_en in CEFR and my_en in CEFR and CEFR.index(need_en) > CEFR.index(my_en):
        flags.append(f"английский {need_en.upper()} (у вас {my_en.upper()})")
    if v.get("has_test") or TEST_TASK_RE.search(full):
        flags.append("тестовое задание")
    if profile.get("is_foreigner") and CITIZEN_KZ_RE.search(full):
        flags.append("только граждане РК")
    if geo_kind == "flag":
        flags.append(geo_why)
    if flags:
        return "flag", flags
    return "keep", []


def score(v, profile):
    s = 0
    text = f"{v.get('title','')} {v.get('description') or v.get('snippet') or ''} {' '.join(v.get('key_skills') or [])}".lower()
    for skill in profile.get("skills", []):
        if skill.lower() in text:
            s += 2
    if v.get("salary_kzt_net"):
        s += 1
    if "REMOTE" in (v.get("work_formats") or []) and "REMOTE" in profile.get("work_formats", []):
        s += 1
    return s


# ───────────────────────── команды ─────────────────────────

def _norm(x):
    return re.sub(r"[^a-zа-яё0-9]+", "", (x or "").lower())


def dedupe(pool):
    """Убирает дубли: тот же id; та же вакансия (название + компания) в разных городах/источниках;
    одинаковые TG-посты с длинным названием в разных каналах. Остаётся первый (hh раньше TG)."""
    seen_ids, seen_keys, out = set(), set(), []
    for v in pool:
        keys = []
        if v.get("company"):
            keys.append("tc:" + _norm(v["title"]) + "|" + _norm(v["company"]))
        if v["source"].startswith("t.me") and len(_norm(v["title"])) >= 20:
            keys.append("tg:" + _norm(v["title"]))
        if v["id"] in seen_ids or any(k in seen_keys for k in keys):
            continue
        seen_ids.add(v["id"])
        seen_keys.update(keys)
        out.append(v)
    return out


def seen_path(profile):
    return os.path.expanduser(profile.get("seen_file", "~/.kz-job-hunter/seen.json"))


def load_seen(profile):
    try:
        with open(seen_path(profile)) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def cmd_search(a):
    with open(a.profile) as f:
        profile = json.load(f)
    sources = (a.sources or ",".join(profile.get("sources", [])) or DEFAULT_SOURCES).split(",")
    log, pool = [], []
    for name in sources:
        fn = SOURCES.get(name.strip())
        if not fn:
            log.append(f"неизвестный источник: {name}")
            continue
        try:
            pool += fn(profile, log)
        except Exception as e:  # noqa: BLE001 — один источник не роняет прогон
            log.append(f"{name}: ошибка {e}")

    pool = dedupe(pool)

    seen = load_seen(profile)
    if a.details:
        prelim = [v for v in pool if v["id"].startswith("hh:") and classify(dict(v), profile, seen)[0] != "drop"]
        for v in prelim[: a.details_limit]:
            hh_details(v, log)
            polite_pause()

    write_run(a.out, profile, pool, seen, log)


def write_run(out_path, profile, pool, seen, log):
    buckets = {"keep": [], "flag": [], "drop": []}
    for v in pool:
        kind, why = classify(v, profile, seen)
        v["reasons"] = why
        v["score"] = score(v, profile)
        v["salary_text"] = fmt_salary(v.get("salary"))
        buckets[kind].append(v)
    for k in ("keep", "flag"):
        buckets[k].sort(key=lambda x: (x["score"], x.get("published") or ""), reverse=True)

    run = {"generated_at": datetime.now(ALMATY_TZ).isoformat(timespec="minutes"),
           "profile_name": profile.get("name", ""), "log": log,
           "counts": {k: len(v) for k, v in buckets.items()}, **buckets}
    with open(out_path, "w") as f:
        json.dump(run, f, ensure_ascii=False, indent=1)
    print(json.dumps({"counts": run["counts"], "log": log}, ensure_ascii=False, indent=1))


def cmd_refilter(a):
    """Перепроверить уже собранный прогон с текущим профилем — без сетевых запросов."""
    with open(a.profile) as f:
        profile = json.load(f)
    with open(a.inp) as f:
        run = json.load(f)
    pool = [v for k in ("keep", "flag", "drop") for v in run[k]]
    pool = [v for v in pool if v.get("reasons") != ["уже видели"]] if a.ignore_seen else pool
    write_run(a.out or a.inp, profile, dedupe(pool), set() if a.ignore_seen else load_seen(profile), run.get("log", []))


MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]


def md_row(v, extra):
    title = v["title"].replace("|", "/").replace("[", "(").replace("]", ")")
    fmt = ", ".join(HH_WORK_FORMAT_RU.get(x, x) for x in v.get("work_formats") or []) or "—"
    return (f"| [{title}]({v['url']}) | {v.get('company') or '—'} | {(v.get('city') or v.get('region') or '—').replace('|', '/')} | "
            f"{fmt} | {v['salary_text']} | {v['source']} | {extra} |")


def cmd_report(a):
    with open(a.inp) as f:
        run = json.load(f)
    now = datetime.fromisoformat(run["generated_at"])
    head = "| Вакансия | Компания | Город | Формат | Зарплата | Источник | {} |\n|---|---|---|---|---|---|---|"
    L = [f"# Вакансии в Казахстане — {now.day} {MONTHS[now.month-1]} {now.year}", "",
         f"Подходящих: **{len(run['keep'])}**, с оговорками: **{len(run['flag'])}**, "
         f"отсеяно: {len(run['drop'])}.", "",
         f"## ✅ Подходят [{len(run['keep'])}]", "", head.format("Совпадений")]
    L += [md_row(v, v["score"]) for v in run["keep"]] or ["| — | | | | | | |"]
    L += ["", f"## ⚠️ С оговорками [{len(run['flag'])}]", "", head.format("Почему")]
    L += [md_row(v, "; ".join(v["reasons"])) for v in run["flag"]] or ["| — | | | | | | |"]
    reasons = {}
    for v in run["drop"]:
        for r in v["reasons"][:1]:
            key = r.split(":")[0].split("(")[0].strip()
            reasons[key] = reasons.get(key, 0) + 1
    L += ["", "## 🚫 Отсеяно", ""] + [f"- {k}: {n}" for k, n in sorted(reasons.items(), key=lambda x: -x[1])]
    L += ["", "## Журнал источников", ""] + [f"- {x}" for x in run["log"]]
    with open(a.out, "w") as f:
        f.write("\n".join(L) + "\n")
    print(a.out)


def cmd_mark_seen(a):
    with open(a.profile) as f:
        profile = json.load(f)
    with open(a.inp) as f:
        run = json.load(f)
    seen = load_seen(profile)
    seen |= {v["id"] for k in ("keep", "flag") for v in run[k]}
    p = seen_path(profile)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(sorted(seen), f)
    print(f"{len(seen)} id в истории: {p}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("--profile", required=True)
    s.add_argument("--out", default="run.json")
    s.add_argument("--sources", default=None, help="через запятую; по умолчанию profile.sources или все: " + DEFAULT_SOURCES)
    s.add_argument("--details", action="store_true", help="подтянуть описания вакансий hh.kz (медленнее, точнее)")
    s.add_argument("--details-limit", type=int, default=60)
    s.set_defaults(fn=cmd_search)
    r = sub.add_parser("report")
    r.add_argument("--in", dest="inp", required=True)
    r.add_argument("--out", default="report.md")
    r.set_defaults(fn=cmd_report)
    rf = sub.add_parser("refilter", help="перепроверить прогон с текущим профилем без запросов к сайтам")
    rf.add_argument("--in", dest="inp", required=True)
    rf.add_argument("--profile", required=True)
    rf.add_argument("--out", default=None)
    rf.add_argument("--ignore-seen", action="store_true")
    rf.set_defaults(fn=cmd_refilter)
    m = sub.add_parser("mark-seen")
    m.add_argument("--in", dest="inp", required=True)
    m.add_argument("--profile", required=True)
    m.set_defaults(fn=cmd_mark_seen)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
