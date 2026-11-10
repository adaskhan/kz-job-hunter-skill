# Источники вакансий

Доступность проверена 11.11.2026 запросом без логина. Группы: Казахстан, СНГ, международная
удалёнка, Affiliate/digital/ИИ, карьерные страницы, Telegram, расширенный поиск в LinkedIn.

Ключ в колонке «Скрипт» — имя источника для `--sources` / `profile.sources`.

---

## 1. Казахстан

| Площадка | Скрипт | Как |
|---|---|---|
| [hh.kz](https://hh.kz) | `hh` | Страница поиска → `HH-Lux-InitialState`. Публичный `api.hh.ru/vacancies` без OAuth отдаёт 403 |
| [enbek.kz](https://www.enbek.kz/ru/search/vacancy) | `enbek` | HTML-карточки. Госбиржа труда: много квазигоссектора, зарплаты gross |
| [OLX Работа](https://www.olx.kz/rabota/) | браузер | Без браузера 403 |
| [Astana Hub](https://astanahub.com) | браузер | Вакансии резидентов технопарка, без браузера 403 |
| [rabota.kz](https://rabota.kz) | браузер | Общий агрегатор |

## 2. СНГ (русскоязычный IT)

| Площадка | Скрипт | Как |
|---|---|---|
| hh.ru: удалёнка по всем странам | `hh` | `hh_sites: {"domain":"hh.ru","work_formats":["REMOTE"]}` без `areas` — вся удалёнка HH, в том числе вакансии из UZ/BY/KG/CY. Удалёнку «только по РФ» отсеивает фильтр |
| hh.uz, rabota.by, cy.hh.ru и т.п. | `hh` | Нужны только для переезда: тот же движок, у каждого домена свой код страны в `areas`: Узбекистан 97, Беларусь 16, Кипр 236, Кыргызстан 48, Армения 13, Грузия 28. hh.ge и hh.am — **другие сайты**, не HH |
| [Habr Career](https://career.habr.com) | `habr` | `career.habr.com/api/frontend/vacancies?q=…&remote=true&sort=date`. Фильтр по Казахстану (`locations[]=ct_527`, Алматы `c_680`) сейчас возвращает 0, поэтому по умолчанию ищем удалёнку |
| [getmatch](https://getmatch.ru) | `getmatch` | `getmatch.ru/api/offers?limit=100&offset=N`. Поиска по тексту на сервере нет: берём свежую ленту и фильтруем сами. Зарплаты net/gross указаны |
| [GeekJob](https://geekjob.ru) | `geekjob` | `geekjob.ru/json/find/vacancy?qs=…` |
| [hirify.me](https://hirify.me) | браузер | ИИ подбирает вакансии под загруженное резюме, нужен логин. Ссылки вида `hirify.me/jobs/{id}` |
| [jobtoo.ru](https://jobtoo.ru) | браузер | Поиск по ключевому слову + фильтр «удалённо» |
| [talent-move.ru](https://talent-move.ru) | браузер | Поиск по ключевому слову + фильтр «удалённо» |

## 3. Международная удалёнка

| Площадка | Скрипт | Как / регион |
|---|---|---|
| [Remote OK](https://remoteok.com) | `remoteok` | `remoteok.com/api` (одна лента). По условиям API в отчёте указываем источник «Remote OK» со ссылкой |
| [Himalayas](https://himalayas.app) | `himalayas` | `himalayas.app/jobs/api/search?q=…`, регион в `locationRestrictions` |
| [We Work Remotely](https://weworkremotely.com) | `wwr` | RSS `remote-jobs.rss`, регион в `<region>` |
| [Working Nomads](https://www.workingnomads.com) | `workingnomads` | `api/exposed_jobs/` (только последние ~40) |
| [Remotive](https://remotive.com) | `remotive` | `api/remote-jobs?search=…`; просят не дёргать чаще нескольких раз в день |
| [Jobicy](https://jobicy.com) | `jobicy` | `api/v2/remote-jobs?tag=…`, регион в `jobGeo` |
| LinkedIn, Indeed, Glassdoor, Wellfound | браузер | Без браузера 403; LinkedIn — см. раздел 6 |
| Daily Remote, JustRemote, Jobgether, Remote.co | браузер | Страницы открываются, открытого API нет |

**Регион найма.** У международных вакансий часто стоит «USA only», «EU only», «UK».
Фильтр `remote_allowed_regions` (регулярка) оставляет worldwide / anywhere / EMEA / Asia / CIS / Kazakhstan.
Вакансии с пустым регионом не отсеиваются. Привязки к часовому поясу вроде «CET ± 3 h»
(Казахстан = UTC+5 = CET+4) по умолчанию отсеиваются; чтобы их оставлять, добавьте в регулярку `time zone`.

## 4. Affiliate-маркетинг, digital, ИИ

| Площадка | Скрипт | Как |
|---|---|---|
| [ArbiHunter](https://arbihunter.com) | браузер | Список вакансий доступен только после логина (`/en/auth?redirectTo=/vacancies`) |
| [AI Jobs](https://aijobs.net) → foorilla.com | браузер | aijobs.net перенаправляет на foorilla.com/hiring |
| Remote OK / Himalayas / Jobicy | скрипт | Для ИИ-ролей добавьте англоязычные ключи: `ml engineer`, `llm`, `ai engineer`, `prompt` |
| TG: @itworkhubchannel, @jobfortm | `tg` | Много ИИ, ML и техменеджмента |

## 5. Карьерные страницы компаний

Скрипт их не обходит: у каждой компании своя вёрстка. Порядок работы:
1. Пользователь называет компании, или Claude предлагает 10–15 крупных работодателей РК под его профиль
   (банки и финтех, e-commerce, телеком, нацкомпании, продуктовые IT-компании Astana Hub).
2. **URL карьерной страницы находим веб-поиском** «{компания} карьера вакансии» и проверяем, что страница открывается.
   Адреса не угадываем: например, `kaspi.kz/career/` отдаёт 404.
3. Проверенный URL сохраняем в `profile.career_pages: [{"company", "url"}]`.
4. При каждом прогоне Claude открывает страницы в браузере и ищет вакансии по ключевым словам профиля.
   У многих компаний вакансии лежат на hh.kz — тогда их уже собрал `hh`, дубли не нужны.

## 6. Telegram

`tg_channels` читаются скриптом через `https://t.me/s/<канал>`: последние ~20 постов,
дубли одного поста в разных каналах убираются. Заголовок вакансии берётся из строки поста,
которая больше всего похожа на название должности.

| Канал | Подписчики | О чём |
|---|---|---|
| [@jobkz_1](https://t.me/jobkz_1) | 38K | Вакансии Казахстана, общие |
| [@workitkz](https://t.me/workitkz) | 37K | IT Казахстан |
| [@devkz_jobs](https://t.me/devkz_jobs) | 26K | IT KZ, теги по городам и стеку |
| [@zhumysbarit](https://t.me/zhumysbarit) | 10K | IT KZ |
| [@it_jobs_kz](https://t.me/it_jobs_kz) | 10K | DSML.KZ — data / ML |
| [@itcom_kz](https://t.me/itcom_kz) | 9K | IT-сообщество KZ |
| [@aitujobs](https://t.me/aitujobs) | 6.5K | Daily Jobs IT KZ (постит реже) |
| [@devkg](https://t.me/devkg) | 23K | IT Кыргызстан |
| [@rabotavmediawe](https://t.me/rabotavmediawe) | 14K | Центральная Азия и мир, медиа |
| [@youritjob](https://t.me/youritjob) | 39K | Сербия и удалёнка |
| [@myresume_ru](https://t.me/myresume_ru) | 20K | Вакансии и стажировки |
| [@devs_it](https://t.me/devs_it) | 19.5K | IT, общий |
| [@job_python](https://t.me/job_python) | 23.5K | Python |
| [@jobfortm](https://t.me/jobfortm) | 15K | Технические менеджеры, тимлиды, CTO |
| [@pythonrabota](https://t.me/pythonrabota) | 13K | Python |
| [@python_vakansii_jobs](https://t.me/python_vakansii_jobs) | 10K | Python |
| [@forpython](https://t.me/forpython) | 7.5K | Python |
| [@relocatesme](https://t.me/relocatesme) | 7K | Релокация |
| [@it_jobs_agregator](https://t.me/it_jobs_agregator) | 2.8K | Агрегатор (постит реже) |
| [@itworkhubchannel](https://t.me/itworkhubchannel) | 2.8K | IT, ML/AI |

**Группы — только через браузер (web.telegram.org под логином пользователя):**

| Группа | Участники | Примечание |
|---|---|---|
| [@cyprusithr](https://t.me/cyprusithr) | 43.5K | CY iT HR: вакансии и резюме, Кипр. У групп нет превью `t.me/s/`. Ссылка на сообщение: ПКМ → «Copy message link» → `https://t.me/cyprusithr/<id>` |

Профильные каналы (Python и т.п.) включайте только под профессию пользователя.
Для другой специальности ищите аналогичные каналы в Фазе 5.

## 7. Расширенный поиск в LinkedIn (браузер, сессия пользователя)

Не ограничиваться разделом Jobs:

1. **Jobs** — `https://www.linkedin.com/jobs/search/?keywords={kw}&location=Kazakhstan&f_TPR=r259200`
   (`f_TPR=r259200` — за 3 дня, `r86400` — за сутки). Для удалёнки: `location=Worldwide` или `EMEA`,
   `f_WT=2` (remote). Сохраняем прямые ссылки `linkedin.com/jobs/view/{id}`.
2. **Посты HR** — `https://www.linkedin.com/search/results/content/?keywords={запрос}&datePosted="past-week"&sortBy="date_posted"`, где запрос:
   - `#hiring {kw} Kazakhstan`, `#hiring {kw} remote`, `#вакансия {kw}`, `#открытавакансия {kw}`,
     `#openrole {kw}`, `#vacancy {kw} Almaty`, `{kw} Алматы вакансия`
   - ссылку на пост берём через «…» → «Copy link to post» (`linkedin.com/posts/…` или `feed/update/urn:li:activity:…`)
3. **Страницы компаний** → вкладка Jobs: для компаний из `career_pages` и для тех, кто часто встречается в отчётах.
4. **Поиск по ключевым словам в постах** — как в п. 2, но без хэштега: `"ищем {kw}"`, `"looking for {kw}"`, `"we are hiring" {kw}`.

Правила: только чтение. Не пишем HR, не ставим лайки, не подписываемся и не откликаемся через Easy Apply
без отдельного «да» пользователя. Капча или проверка безопасности → стоп, LinkedIn в этом прогоне пропускаем.
Не больше ~30 просмотров страниц за прогон.
