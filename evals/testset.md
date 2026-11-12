# Test set, readable

A view of `testset.jsonl` for checking it by hand. Each row: the question, the answer a right
system gives, the documents it must cite (and must not), and the facts the deterministic check
looks for. Mark wrong rows, and the JSONL gets fixed; `verified` records the check.

| Id | Type | Question | Expected answer | Sources | Must not cite | Key facts | Verified |
|---|---|---|---|---|---|---|---|
| q01 | trap | Чи розглядає RenovateHub на позицію Trainee/Junior Python/Django кандидатів без досвіду? | Так: у вакансії від 17.02.2025 вказано «від 0.5 років досвіду» і «також розглядаємо без досвіду». | djinni-720067 | djinni-709945 | без досвіду | no |
| q02 | answerable | On which days and at what hours does Elogic's junior Python developer work? | Only on weekends, Saturday and Sunday, from 7:00 to 23:00. | djinni-730767 | – | saturday; sunday; 7:00; 23:00 | no |
| q03 | answerable | What Dutch and English levels does PEXLY require from its Python developer? | Dutch at C2 and English at B2. | djinni-762194 | – | c2; b2 | no |
| q04 | answerable | Які протоколи передачі даних згадано у вакансії Python Developer (IOT) від Eleven? | MQTT та HTTP. | djinni-816082 | – | mqtt; http | no |
| q05 | trap | How many years of experience does DataArt require for a Senior Python Developer? | The current posting (April 2026, Senior Python Developer with experience in Django and AWS) asks for 6+ years of professional engineering experience. A 2019 posting asked for 3 years or more. | djinni-819462 | – | 6+ / 6 years / six years | no |
| q06 | answerable | What anti-bot measures should Meta Sistem's Python web crawling specialist be able to handle? | Website restrictions, CAPTCHAs and other anti-bot measures; the posting also asks for proxy management and headless browsers. | djinni-731104 | – | captcha | no |
| q07 | answerable | Besides English, which language is an advantage for the Python Developer at DocStudio? | Spoken German is an advantage; B2 or C1 English is mandatory. | djinni-726177 | – | german | no |
| q08 | answerable | Які брокери повідомлень використовує Senior Python Backend Developer у Performa HR-agency? | NATS JetStream і Kafka; кандидату потрібен досвід хоча б з одним із брокерів Kafka, NATS або RabbitMQ. | djinni-842647 | – | nats; kafka | no |
| q09 | answerable | What is the maximum salary for Keymakr's Junior Python Software Engineer? | Up to $700 a month. | djinni-764691 | – | 700 | no |
| q10 | trap | What English level does Proxet require for the Senior Backend Engineer (Python)? | B2 (Upper-Intermediate), and professional proficiency in English and Ukrainian for customer meetings. | djinni-854534 | – | b2 / upper | no |
| q11 | trap | What English level does Sigma Software ask from Python developers now? | Upper-Intermediate (B2): the 2025 and 2026 postings ask for it. A 2019 posting asked for Intermediate. | djinni-851569, djinni-772946 | – | upper / b2 | no |
| q12 | trap | Скільки років досвіду потрібно для Middle Python Developer в Ajax Systems? | Від 2 років комерційної розробки (вакансія від 16.10.2026). | djinni-853661 | djinni-159551, djinni-712774 | 2 років / 2 роки / двох років / 2 years / two years | no |
| q13 | answerable | У якому часовому поясі працюватиме Agentic Engineer / Technical Lead у Temy? | За часовим поясом Великої Британії (UK time-zone): це проєкт з Великої Британії. | djinni-852724 | – | uk time / британ | no |
| u01 | unanswerable | What salary does Proxet offer for the Senior Backend Engineer (Python)? | The documents don't say: the posting gives no salary. | – | – | – | no |
| u02 | unanswerable | Чи надає Honeytech працівникам службовий автомобіль? | У документах цього немає: серед переваг Honeytech автомобіля немає. | – | – | – | no |
| u03 | unanswerable | How much does Luxoft pay a Rust developer? | The documents don't say: there is no Rust posting. | – | – | – | no |
| u04 | unanswerable | Does GlobalLogic's Middle/Senior Python Engineer posting offer relocation to Canada? | The documents don't say. | – | – | – | no |
| u05 | unanswerable | Яка мінімальна заробітна плата в Україні у 2027 році? | У документах цього немає. | – | – | – | no |
| o01 | trap | Якою має бути зарплата заброньованого працівника критично важливого підприємства? | Не нижче мінімальної зарплати, помноженої на коефіцієнт 3: постанова № 692 від 30.05.2026 замінила коефіцієнт 2,5 на 3. Коефіцієнт 2,5 лишився для критично важливих підприємств на територіях можливих чи активних бойових дій і тимчасово окупованих. Роз'яснення Запорізької ОДА від березня 2026 року ще називає загальний коефіцієнт 2,5. | reservation-resolution-692-amendments-to-76-2026-05-30 | – | коефіцієнт 3 / цифрою 3 / 3 мінімальн / трьох мінімальн / 3 розмір / помноженої на 3 / в 3 рази / у 3 рази / 3 рази | no |
| o02 | answerable | Як за листом Мінекономіки від 07.08.2026 рахувати середню зарплату для критерію критично важливого підприємства? | За новою формою Податкового розрахунку: суму рядків 1.1 (нарахована зарплата), 1.3 і 1.4 (оплата перших 5 днів і допомога по тимчасовій непрацездатності) поділити на рядок 092 (кількість працівників, яким нараховано зарплату). | reservation-average-salary-letter-minekonomiky-2026-08-07 | – | 1.1; 092 | no |
| o03 | answerable | Що таке призупинення дії трудового договору? | Тимчасове припинення роботодавцем забезпечення працівника роботою і тимчасове припинення працівником виконання роботи за трудовим договором у зв'язку зі збройною агресією проти України, що виключає можливість обох сторін виконувати свої обов'язки (стаття 13 Закону № 2136-IX). | martial-law-labour-relations-supreme-court-2025-12-24 | – | тимчасове припинення; агресі | no |
| o04 | answerable | Can a Diia City resident be recognised as a critical enterprise so that its staff can be reserved? | Yes. As worded by Resolution 692 of 30 May 2026, one criterion is that the company is a Diia City resident meeting point 2 of part 1 of article 5 of the Law on stimulating the digital economy, confirmed by its tax calculations for the last six calendar months. | reservation-resolution-692-amendments-to-76-2026-05-30 | – | resident / резидент; six / 6 months / 6 calendar / шість | no |
| o05 | answerable | Які види діяльності пропонували додати до переліку Дія Сіті у 2024 році? | Ремонт і технічне обслуговування електронних компонентів, комп'ютерів, обладнання зв'язку, вимірювальних і оптичних приладів; виробництво батарей і акумуляторів до безпілотних апаратів; дослідження кон'юнктури ринку та інтернет-аналітику для маркетингових кампаній (пояснювальна записка Мінцифри від 04.11.2024). | diia-city-activities-list-explanatory-note-2024-11-04 | – | ремонт; батар / акумулятор | no |
| o06 | trap | Який строк дії відстрочки вказувати в нових посвідченнях при переоформленні бронювання за листом Мінекономіки? | «На шість місяців»: так у чинній редакції листа від 10.01.2024. Редакція від 18.08.2023 розрізняла строк мобілізації для державних і місцевих органів і шість місяців для підприємств. | reservation-reissue-letter-minekonomiky-2024-01-10 | reservation-reissue-letter-minekonomiky-2023-08-18 | шість місяців / 6 місяців / six months | no |
| o07 | answerable | Як підприємство звіряє списки військового обліку з ТЦК, якщо воно розташоване за межами зони відповідальності цього ТЦК? | Надсилає до РТЦК та СП два примірники витягів зі списків персонального військового обліку і копії військово-облікових документів; ТЦК протягом 3 діб звіряє і повертає примірник витягу з відміткою. Звіряння проводять за пунктом 46 постанови № 1487, за затвердженим графіком. | military-registration-reconciliation-algorithm-zaporizhzhia-2026-07-17 | – | два примірники / 2 примірники; 3-х діб / 3 діб / трьох діб / 3 дн / три доби | no |
| o08 | unanswerable | Яка ставка єдиного податку для ФОП третьої групи у 2026 році? | У документах цього немає. | – | – | – | no |

## Retrieval questions

From `retrieval.jsonl`: the passage that answers each, as a document and a quote.

| Id | Kind | Question | Document | Quote |
|---|---|---|---|---|
| r01 | named | Чи розглядає RenovateHub на позицію Trainee/Junior Python/Django кандидатів без досвіду? | djinni-720067 | Також розглядаємо без досвіду |
| r02 | named | Скільки років комерційного досвіду потрібно для Middle Python Developer в Ajax Systems? | djinni-853661 | досвід комерційної розробки від 2 років |
| r03 | cross-language | Де Python-розробнику потрібна нідерландська мова на рівні носія? | djinni-762194 | Dutch C2 |
| r04 | cross-language | Яка вакансія пропонує переїзд до Португалії? | djinni-750869 | relocation to Portugal |
| r05 | cross-language | Де молодший Python-розробник працює лише у вихідні дні? | djinni-730767 | Saturday and Sunday |
| r06 | cross-language | Which posting is about embedded software for Linux-based IoT devices? | djinni-816082 | IoT-пристроїв на базі Linux |
| r07 | cross-language | Which backend role integrates cryptocurrency exchanges? | djinni-842647 | ccxt та API криптобірж |
| r08 | paraphrased | Which job involves getting past website bot protection while collecting data? | djinni-731104 | anti-bot measures |
| r09 | paraphrased | Which company builds simulation software that helps governments make decisions? | djinni-854534 | simulation and decision-support |
| r10 | paraphrased | Which job wants someone who builds plugins and MCP servers for AI coding assistants? | djinni-852724 | MCP-серверів або плагінів |
| r11 | paraphrased | Where can a developer with no commercial experience at all apply for a Django job? | djinni-720067 | Також розглядаємо без досвіду |
| r12 | named | Як постанова № 692 змінила коефіцієнт мінімальної зарплати для заброньованих працівників? | reservation-resolution-692-amendments-to-76-2026-05-30 | цифри “2,5” замінити цифрою “3” |
| r13 | cross-language | How is the average salary for the critical-enterprise criterion computed from the new tax form? | reservation-average-salary-letter-minekonomiky-2026-08-07 | рядок 092 |
| r14 | paraphrased | Що означає, коли роботодавець тимчасово не дає працівникові роботу через війну? | martial-law-labour-relations-supreme-court-2025-12-24 | тимчасове припинення роботодавцем забезпечення працівника роботою |
| r15 | cross-language | Can a Diia City resident qualify as a critical enterprise to reserve its staff? | reservation-resolution-692-amendments-to-76-2026-05-30 | є резидентом Дія Сіті |
