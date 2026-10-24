# Golden set

The 30 job postings in `data/texts/job/` are all Djinni Python postings from 2025–2026, and
each has a label in `data/golden/job/<doc_id>.json`. The models are scored against these
labels (`python main.py eval`), so a label says what the posting says, not what a model would
answer. They were picked for variety with a fixed seed: Ukrainian and English, 1,100 to 8,800
characters, trainee to lead, ten with a salary.

Claude Code wrote all 30 labels by the rules below, and a person checks each one against its
posting on the labelling page. `data/golden/verified.txt` lists the checked postings, and
`data/golden/claude/job/` keeps Claude's labels as written, so the page can show what each
check changed. Until a label is checked, accuracy against it is accuracy against Claude.

The schema (`src/extraction/schemas.py`) follows what Djinni records. Its fact lines at the end
of each text (work format, countries, experience, English, employment, domain, company type)
are fixed values, in Ukrainian or English depending on the page, and the schema's enums are
Djinni's own: from its job filters and the 1,051 postings of 2025–2026.

## Checking the labels

Run `make label` (or `python main.py label`). It opens a page in your browser with one posting
beside a form holding its label. Correct what's wrong, if anything, and **Save** (⌘S): that
writes `data/golden/job/<doc_id>.json` and marks the posting verified. No files to find or ids
to match.

- The page opens at the first posting not verified yet; the arrows and the list move between
  them, and ✓ marks the verified ones.
- Every enum is a dropdown. A hard skill's field searches the names postings use: typing
  "postgres" offers `postgresql`, and "unit tests" offers `testing`.
- **+ Selected text** adds the words you selected in the posting as a hard skill, with its id
  filled in when the words are a name the list knows. Enter in a text cell adds a row.
- Saving checks the label against the schema and against the rules below the schema can't
  check, such as a level for every skill. A label that fails is not written.
- Unsaved work is kept as a draft in the browser, so leaving a posting half done loses
  nothing. A draft shows in place of the label on disk until it's saved.
- Once a posting is verified, the page shows where your label differs from Claude's,
  scored the way `eval` scores a model, with yours as the answer. The badge at the top keeps
  the agreement over all verified postings: how far Claude's labels can be trusted.

`python main.py check` validates every label again.

## The posting

| Field | Rule |
|---|---|
| `title` | The title as the posting gives it, in English: `АІ engineer` (Cyrillic АІ) is `AI Engineer`, `Python / Django розробник` is `Python / Django Developer`. Drop reference codes such as `IRC280820`. |
| `seniority` | Named in the title or the text: Trainee or Intern is `intern`; Strong Junior is `junior`; Middle+ and Strong Middle are `middle`; Team Lead, Tech Lead, Head of, Principal and Architect are `lead`. With two levels (`Middle/Senior`), the lower one. `null` when none is named, even if years are. |
| `company_type` | Djinni's line: Продуктова is `product`, Сервісна or Аутсорсингова (Outsource) is `outsource`, Аутстафінгова is `outstaff`, Стартап is `startup`, Агенція is `agency`, Змішана (сервісно-продуктова) is `mixed`. |
| `domain` | Djinni's `Домен:` line: Machine Learning / Big Data is `ml`, DefTech is `miltech`, Education is `edutech`, Blockchain / Crypto is `crypto`, Hardware / IoT is `hardware`, Healthcare / MedTech is `healthcare`, Other is `other`. |
| `employment` | `Зайнятість: Fulltime` is `full_time`, `Неповна / Парт-тайм` is `part_time`. |
| `work_formats` | `Тільки віддалено` (Full Remote) is `remote`, `Тільки офіс` (Office Work) is `office`, `Гібридний формат роботи` (Hybrid Remote) is `hybrid`. Every one the posting allows: `Офіс або віддалено` is office and remote, and so is a text that offers an office besides Djinni's `Тільки віддалено`. |
| `candidate_location` | The line above `Країни, де розглядаємо кандидатів`: Україна is `ukraine`, Країни Європи та Україна is `europe_and_ukraine`, Країни ЄС is `eu`, Весь світ (Worldwide) is `worldwide`, and a list of countries is `countries`. |
| `candidate_countries` | With `countries`, their ISO codes: `Польща, Румунія` is `POL, ROU`. Otherwise empty. |
| `office_cities` | The cities whose office the job can be worked from, in English: `(Київ)` under `Офіс:` is `Kyiv`. |
| `min_experience_years` | The fewest years accepted: `від 6 років` with `також розглядаємо з досвідом 5 років` is 5; `Без досвіду` and `також розглядаємо без досвіду` are 0. |
| `salary` | Djinni's range (`$1350-2600`), monthly, in its currency; without a range, the header: `до $2600` is a maximum only. `Розглядаємо до $3100` is room to negotiate, not the range. |

## Requirements

Everything the posting asks of the candidate goes into one of five lists. That means the
requirements and nice-to-haves in the text, Djinni's `Необхідні навички` line (with years, as
in `Python: 6 років`) and its language lines.

These are not requirements:
- the job's duties ("you will build APIs with FastAPI");
- what the company offers, including a ФОП contract listed under the offer;
- how to apply: a test task, or a GitHub link in the first message;
- statements too general to check: "thinks in systems", "wants to stay hands-on".

An introduction that describes the candidate ("a Senior Engineer with strong architecture
expertise") does count.

**`hard_skills`** take an id from the list below; `other` when none fits, with the words in
`name`.
- One item per id. Things that share an id are one item, at the higher level: REST API and
  OpenAPI are both `rest_api`, Lambda and S3 are both `aws`.
- Alternatives are an item each: `AWS/GCP/Azure` is aws, gcp and azure, with the line's level
  and must-have.
- Tools named in brackets or after "such as" are the items: `MLOps practices (MLflow, Docker,
  CI/CD, Kubernetes)` is mlops, docker, ci_cd and kubernetes.
- `other` items from one line are one item, their names together: `Time series, recommender
  systems`. A required degree is `other` too.
- "Preferably X" is not a must, unless Djinni's skills line lists X.
- `name` is the skill as the posting writes it, in English.
- `years` only when the posting ties them to this skill: Djinni's `Python: 6 років`, "3+ years
  of Django", "7+ years in backend development with Python". The posting's overall years go
  to `min_experience_years`.

| Area | Ids |
|---|---|
| Languages | `python`, `sql`, `javascript`, `typescript`, `go`, `java`, `kotlin`, `csharp`, `cpp`, `rust`, `php`, `ruby`, `scala`, `bash` |
| Backend | `django`, `drf`, `fastapi`, `flask`, `aiohttp`, `sqlalchemy`, `pydantic`, `nodejs`, `async_programming` |
| APIs | `rest_api`, `graphql`, `grpc`, `websockets` |
| Databases | `postgresql`, `mysql`, `mongodb`, `redis`, `elasticsearch`, `clickhouse`, `nosql`, `orm`, `database_design` |
| Queues | `kafka`, `rabbitmq`, `celery`, `message_queues` |
| Cloud | `aws`, `gcp`, `azure`, `cloud` |
| DevOps | `docker`, `kubernetes`, `terraform`, `ci_cd`, `linux`, `nginx`, `observability`, `networking` |
| Testing | `testing`, `pytest`, `selenium`, `playwright` |
| Design & architecture | `software_design` (OOP, SOLID, patterns, clean code), `software_architecture` (microservices, distributed systems, system design), `algorithms` |
| ML & data science | `machine_learning`, `nlp`, `computer_vision`, `pandas`, `numpy`, `scikit_learn`, `pytorch`, `tensorflow`, `data_analysis`, `mlops` |
| LLM & GenAI | `ai`, `llm`, `rag`, `ai_agents`, `langchain`, `hugging_face`, `ai_coding_tools` |
| Data engineering | `etl`, `airflow`, `spark`, `data_warehouse` |
| Web scraping | `web_scraping` |
| Frontend | `react`, `angular`, `vue`, `html_css` |
| Security | `security` |
| Tools & process | `git`, `agile` |

The names each id stands for are in `src/extraction/skills.py`, and the page searches them.

**`level`**, for hard and soft skills, is how well the candidate must know it:

| Level | Means | Typical wording | Years |
|---|---|---|---|
| `basic` | knows the basics | basic, familiarity, understanding of | |
| `junior` | has used it, with help | experience with, knowledge of, practice | 1 |
| `middle` | works with it on their own | good, solid, confident, proficient | 2–4 |
| `senior` | knows it in depth, designs with it | strong, deep, advanced, in-depth | 5+ |
| `expert` | an authority | expert, expertise, mastery | |

- The wording and the years decide; take the higher of the two. Hands-on and practical
  experience are `middle`; a strong understanding or a deep grasp is `senior`.
- With neither, a skill takes the role's level when it is the role's main skill: in the
  title, or marked important. Any other skill goes one level lower, nice-to-haves included.
- A skill in the title is never below the role's level, whatever the wording.
- The role's level is its seniority, and a lead role's is `senior`. When no seniority is
  named, it comes from the years: 0–1 is junior, 2–4 middle, 5+ senior.
- Soft skills are `middle` when only named, and `senior` for "strong", "excellent", "high"
  or "proven".

**`soft_skills`** take one of: `communication`, `teamwork` (non-conflict too), `ownership`
(responsibility, autonomy), `problem_solving`, `analytical_thinking`, `critical_thinking`,
`self_learning`, `attention_to_detail` (diligence, accuracy), `time_management`
(punctuality), `proactivity`, `result_orientation`, `leadership`, `mentoring`,
`adaptability`, `stress_resistance`, `customer_focus`, or `other`.

**`languages`**: English included.
- `level` is the lowest one accepted: `B2 / C1 English is mandatory` is b2, even if Djinni's
  line says C1.
- Носій мови is `native`; "spoken German" and "professional proficiency" have no level.
- English that the text lists only as preferred is not a must, even when Djinni's line gives
  its level.

**`domain_experience`** is experience in a business domain, from Djinni's domains: its
`Fintech: 3 роки` rows, or "experience in healthcare is a plus". The posting's own
`Домен:` line isn't one.

**`legal`** holds conditions, not abilities:
- `time_zone`: hours the candidate must keep, with the zone or the hours in `detail`
  (`Weekends 7:00-23:00 GMT+3`); an office schedule listed in the offer isn't one,
- `work_permit`, `citizenship`,
- `military_registration` (documents or a deferment),
- `contract_type` (FOP, B2B: when required, not when offered),
- `age`, `background_check`, `relocation`, `business_travel`, `other`.

Where candidates may be lives in `candidate_location`, not here.

**`must_have`** is false only when the posting says so: nice to have, a plus, bonus,
advantage, optional, буде плюсом, буде перевагою, вітається.

## Notes on some labels

The calls that took judgement, worth a look first when checking.

- [djinni-854590](claude/job/djinni-854590.json), Ukrainian, ML.
  - `1+ рік у сфері ML / data science / applied AI` is `machine_learning`, junior, 1 year.
  - `Впевнене володіння Python і бібліотеками (...)` makes Python and each library middle.
  - The MLOps tools come with `розуміння` (basic) and `буде плюсом` (not a must).
  - Time series and recommender systems are one `other` item.
  - Seniority is null although a year is asked.
- [djinni-827023](claude/job/djinni-827023.json), English, senior.
  - FastAPI, GCP and PostgreSQL appear only in the duties, so they're left out.
  - `7+ years ... with Python` is senior with 7 years.
  - `Expertise in software architecture and design patterns` is expert in both.
  - `Proficiency with Docker` is middle.
  - The medical and sports bonus becomes domain experience, not a must.
- [djinni-712120](claude/job/djinni-712120.json), Ukrainian, trainee.
  - `Trainee/Junior` is intern, and `також розглядаємо без досвіду` is 0 years.
  - HTML5, CSS3 and Bootstrap5 share `html_css`.
  - Djinni's skills PostgreSQL, Docker and Agile carry no wording, so they sit one level below junior, at basic.
  - HTMX and Alpine.js are one `other` item, not a must: `вітається`.
  - The GitHub-repo rule and the ФОП line aren't requirements.
- [djinni-726177](claude/job/djinni-726177.json), English, with salary.
  - The starred "important" skills are senior, from 5–6 years; the rest are middle.
  - English is b2 because the text accepts B2.
  - German has no level.
  - The personal characteristics map to soft skills, with "high rate of self-study" as senior.
- [djinni-706772](claude/job/djinni-706772.json), English, short.
  - `work during EST time` is a `time_zone` condition.
  - `Виключно від 6 років` makes the title's skills senior and the rest middle.
  - The "other optional backgrounds" are junior and not a must.
- [djinni-780925](claude/job/djinni-780925.json): the Bachelor's degree is `other`.
- [djinni-852050](claude/job/djinni-852050.json): the Austrian work permit, the citizenship
  rule and the daily office in Vienna are `legal`.
- [djinni-852724](claude/job/djinni-852724.json), lead.
  - Djinni's line says remote only, but the text also offers the offices in Lviv and Kyiv, so
    the work formats are office and remote.
  - `Agentic Engineer` in the title makes `ai_agents` senior, as for a lead role.
- [djinni-854360](claude/job/djinni-854360.json) and
  [djinni-854363](claude/job/djinni-854363.json): English sits under Preferred, so it isn't a
  must.
- [djinni-854516](claude/job/djinni-854516.json), Ukrainian.
  - `сильною архітектурною ... експертизою` in the introduction makes `software_architecture`
    expert.
  - Python is in the title, so it's senior, though `Впевнене володіння` alone would be middle.
- [djinni-854534](claude/job/djinni-854534.json): `strong hands-on expertise in Python` is
  expert; PostgreSQL is preferred, so not a must; visiting customer sites is
  `business_travel`.

## The postings

| Posting | Date | Title | Language | Characters | Salary |
|---|---|---|---|--:|---|
| [djinni-37050](../texts/job/djinni-37050.txt) | 2026-10 | Python Engineer | en | 2,196 |  |
| [djinni-706772](../texts/job/djinni-706772.txt) | 2025-01 | Full-stack Python / Typescript (React) - work during EST time | en | 1,105 |  |
| [djinni-712120](../texts/job/djinni-712120.txt) | 2025-01 | Trainee/Junior Python/Django developer | ua | 2,263 | до $350 |
| [djinni-719228](../texts/job/djinni-719228.txt) | 2025-02 | Senior Python Engineer | en | 3,587 | до $7000 |
| [djinni-726177](../texts/job/djinni-726177.txt) | 2025-03 | Python Developer | en | 1,114 | до $4500 |
| [djinni-727693](../texts/job/djinni-727693.txt) | 2025-04 | Senior Python Developer | en | 2,108 | до $3500 |
| [djinni-730269](../texts/job/djinni-730269.txt) | 2025-04 | Python AI multi-agent engineer | ua | 4,292 |  |
| [djinni-730756](../texts/job/djinni-730756.txt) | 2025-04 | Middle/Middle Strong Python Developer (Fintech platform) | en | 2,318 | до $4000 |
| [djinni-730767](../texts/job/djinni-730767.txt) | 2025-04 | Junior Python Developer (work only on weekends) | en | 2,266 | до $400 |
| [djinni-731104](../texts/job/djinni-731104.txt) | 2025-04 | Python Web Crawling Specialist | en | 1,595 |  |
| [djinni-744638](../texts/job/djinni-744638.txt) | 2025-06 | Python Developer (Middle+) — Internal Product | en | 3,626 | до $4000 |
| [djinni-762194](../texts/job/djinni-762194.txt) | 2025-08 | Dutch speaking Python Developer | en | 8,795 |  |
| [djinni-764691](../texts/job/djinni-764691.txt) | 2025-08 | Junior Python Software Engineer | en | 2,749 | до $700 |
| [djinni-772946](../texts/job/djinni-772946.txt) | 2025-10 | Senior Python Developer (AdTech) | mixed | 4,813 |  |
| [djinni-780925](../texts/job/djinni-780925.txt) | 2025-11 | Lead Python AWS Cloud Engineer IRC280820 | en | 3,876 |  |
| [djinni-794469](../texts/job/djinni-794469.txt) | 2026-01 | Python / Django розробник | ua | 1,255 |  |
| [djinni-816082](../texts/job/djinni-816082.txt) | 2026-03 | Python Developer (IOT) | ua | 2,312 |  |
| [djinni-819872](../texts/job/djinni-819872.txt) | 2026-04 | Python Developer — Automation Platform (Middle to Senior) | en | 6,043 | до $4500 |
| [djinni-827023](../texts/job/djinni-827023.txt) | 2026-10 | Senior Python Developer | en | 3,844 |  |
| [djinni-842580](../texts/job/djinni-842580.txt) | 2026-08 | Strong Middle AI Engineer | en | 3,175 | до $4000 |
| [djinni-842647](../texts/job/djinni-842647.txt) | 2026-10 | Senior Python Backend Developer | ua | 2,741 |  |
| [djinni-846467](../texts/job/djinni-846467.txt) | 2026-10 | Senior Backend Developer (Python/Docker) | en | 3,566 |  |
| [djinni-852050](../texts/job/djinni-852050.txt) | 2026-10 | Senior Python Developer | en | 1,467 |  |
| [djinni-852724](../texts/job/djinni-852724.txt) | 2026-10 | Agentic Engineer / Technical Lead | ua | 4,015 |  |
| [djinni-854358](../texts/job/djinni-854358.txt) | 2026-10 | AI / LLM Engineer (Python) | en | 2,439 |  |
| [djinni-854360](../texts/job/djinni-854360.txt) | 2026-10 | Python Backend Engineer | en | 2,287 |  |
| [djinni-854363](../texts/job/djinni-854363.txt) | 2026-10 | AI Automation Engineer | en | 2,339 |  |
| [djinni-854516](../texts/job/djinni-854516.txt) | 2026-10 | Senior Software Engineer (Python) | ua | 5,230 |  |
| [djinni-854534](../texts/job/djinni-854534.txt) | 2026-10 | Senior Backend Engineer (Python) | en | 4,573 |  |
| [djinni-854590](../texts/job/djinni-854590.txt) | 2026-10 | АІ engineer | ua | 1,495 |  |
