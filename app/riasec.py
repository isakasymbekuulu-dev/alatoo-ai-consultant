"""RIASEC (Holland) career interest test.

Adaptation of the O*NET Interest Profiler Short Form (Rounds, Su, Lewis &
Rivkin, 2010; U.S. Department of Labor, public domain): 60 items, 10 per
RIASEC type, 5-point Likert scale (1 = strongly dislike ... 5 = strongly like).

Scoring: sum per type (10..50). Holland code = top-3 letters (ties broken by
canonical R-I-A-S-E-C order). Recommendations: Ala-Too bachelor programs are
tagged with 3-letter Holland codes; match = weighted congruence between the
user's normalized profile and the program code (weights 3/2/1).
"""
import uuid
from typing import Dict, List

RIASEC_ORDER = "RIASEC"

TYPES = {
    "R": {
        "ru": {"name": "Реалистический", "desc": "Практик: техника, инструменты, работа руками, конкретный результат."},
        "ky": {"name": "Реалисттик", "desc": "Практик: техника, аспаптар, кол менен иштөө, так натыйжа."},
        "en": {"name": "Realistic", "desc": "Doer: tools, machines, hands-on work, tangible results."},
    },
    "I": {
        "ru": {"name": "Исследовательский", "desc": "Мыслитель: анализ, наука, эксперименты, решение сложных задач."},
        "ky": {"name": "Изилдөөчүлүк", "desc": "Ойчул: анализ, илим, эксперименттер, татаал маселелерди чечүү."},
        "en": {"name": "Investigative", "desc": "Thinker: analysis, science, experiments, solving complex problems."},
    },
    "A": {
        "ru": {"name": "Артистический", "desc": "Творец: дизайн, тексты, музыка, самовыражение, нестандартные идеи."},
        "ky": {"name": "Артисттик", "desc": "Чыгармачыл: дизайн, текст, музыка, өзүн көрсөтүү, жаңы идеялар."},
        "en": {"name": "Artistic", "desc": "Creator: design, writing, music, self-expression, original ideas."},
    },
    "S": {
        "ru": {"name": "Социальный", "desc": "Помощник: обучение, поддержка людей, общение, командная работа."},
        "ky": {"name": "Социалдык", "desc": "Жардамчы: окутуу, адамдарды колдоо, баарлашуу, командалык иш."},
        "en": {"name": "Social", "desc": "Helper: teaching, supporting people, communication, teamwork."},
    },
    "E": {
        "ru": {"name": "Предприимчивый", "desc": "Лидер: управление, переговоры, бизнес, влияние и инициатива."},
        "ky": {"name": "Ишкердик", "desc": "Лидер: башкаруу, сүйлөшүүлөр, бизнес, таасир жана демилге."},
        "en": {"name": "Enterprising", "desc": "Persuader: management, negotiation, business, influence, initiative."},
    },
    "C": {
        "ru": {"name": "Конвенциональный", "desc": "Организатор: порядок, данные, учёт, точность, чёткие процедуры."},
        "ky": {"name": "Конвенциялык", "desc": "Уюштуруучу: тартип, маалымат, эсеп, тактык, так эрежелер."},
        "en": {"name": "Conventional", "desc": "Organizer: order, data, records, accuracy, clear procedures."},
    },
}

# (type, en, ru, ky) — O*NET Interest Profiler Short Form items.
_RAW_ITEMS = [
    # Realistic
    ("R", "Build kitchen cabinets", "Собирать кухонные шкафы", "Ашкана шкафтарын куроо"),
    ("R", "Lay brick or tile", "Класть кирпич или плитку", "Кыш же плитка төшөө"),
    ("R", "Repair household appliances", "Ремонтировать бытовую технику", "Тиричилик техникасын оңдоо"),
    ("R", "Raise fish in a fish hatchery", "Разводить рыбу в рыбном хозяйстве", "Балык чарбасында балык өстүрүү"),
    ("R", "Assemble electronic parts", "Собирать электронные компоненты", "Электрондук бөлүктөрдү чогултуу"),
    ("R", "Drive a truck to deliver packages to offices and homes", "Водить грузовик и доставлять посылки по адресам", "Жүк ташуучу унаа айдап, посылкаларды жеткирүү"),
    ("R", "Test the quality of parts before shipment", "Проверять качество деталей перед отправкой", "Жөнөтүүдөн мурун тетиктердин сапатын текшерүү"),
    ("R", "Repair and install locks", "Устанавливать и ремонтировать замки", "Кулпуларды орнотуу жана оңдоо"),
    ("R", "Set up and operate machines to make products", "Настраивать станки и производить на них продукцию", "Станокторду жөндөп, продукция чыгаруу"),
    ("R", "Put out forest fires", "Тушить лесные пожары", "Токой өрттөрүн өчүрүү"),
    # Investigative
    ("I", "Develop a new medicine", "Разрабатывать новое лекарство", "Жаңы дары иштеп чыгуу"),
    ("I", "Study ways to reduce water pollution", "Изучать способы уменьшения загрязнения воды", "Суунун булганышын азайтуу жолдорун изилдөө"),
    ("I", "Conduct chemical experiments", "Проводить химические эксперименты", "Химиялык эксперименттерди жүргүзүү"),
    ("I", "Study the movement of planets", "Изучать движение планет", "Планеталардын кыймылын изилдөө"),
    ("I", "Examine blood samples using a microscope", "Исследовать образцы крови под микроскопом", "Кан үлгүлөрүн микроскоп менен изилдөө"),
    ("I", "Investigate the cause of a fire", "Расследовать причину пожара", "Өрттүн себебин иликтөө"),
    ("I", "Develop a way to better predict the weather", "Разрабатывать способ точнее предсказывать погоду", "Аба ырайын тагыраак алдын ала айтуу ыкмасын иштеп чыгуу"),
    ("I", "Work in a biology lab", "Работать в биологической лаборатории", "Биология лабораториясында иштөө"),
    ("I", "Invent a replacement for sugar", "Изобрести заменитель сахара", "Канттын алмаштыргычын ойлоп табуу"),
    ("I", "Do laboratory tests to identify diseases", "Проводить лабораторные анализы для выявления болезней", "Ооруларды аныктоо үчүн лабораториялык анализ жүргүзүү"),
    # Artistic
    ("A", "Write books or plays", "Писать книги или пьесы", "Китеп же пьеса жазуу"),
    ("A", "Play a musical instrument", "Играть на музыкальном инструменте", "Музыкалык аспапта ойноо"),
    ("A", "Compose or arrange music", "Сочинять или аранжировать музыку", "Музыка жазуу же аранжировка жасоо"),
    ("A", "Draw pictures", "Рисовать картины и иллюстрации", "Сүрөт тартуу"),
    ("A", "Create special effects for movies", "Создавать спецэффекты для фильмов", "Кинолорго атайын эффекттерди жасоо"),
    ("A", "Paint sets for plays", "Оформлять декорации для спектаклей", "Спектаклдерге декорация жасалгалоо"),
    ("A", "Write scripts for movies or television shows", "Писать сценарии для кино и телешоу", "Кино жана телешоулорго сценарий жазуу"),
    ("A", "Perform jazz or tap dance", "Танцевать джаз или степ", "Джаз же степ бийин аткаруу"),
    ("A", "Sing in a band", "Петь в музыкальной группе", "Музыкалык топто ырдоо"),
    ("A", "Edit movies", "Монтировать фильмы", "Кинолорду монтаждоо"),
    # Social
    ("S", "Teach an individual an exercise routine", "Обучать человека комплексу упражнений", "Адамга көнүгүүлөр комплексин үйрөтүү"),
    ("S", "Help people with personal or emotional problems", "Помогать людям с личными и эмоциональными проблемами", "Адамдарга жеке жана эмоциялык көйгөйлөрүндө жардам берүү"),
    ("S", "Give career guidance to people", "Консультировать людей по выбору профессии", "Адамдарга кесип тандоодо кеңеш берүү"),
    ("S", "Perform rehabilitation therapy", "Проводить реабилитационную терапию", "Реабилитациялык терапия жүргүзүү"),
    ("S", "Do volunteer work at a non-profit organization", "Работать волонтёром в некоммерческой организации", "Коммерциялык эмес уюмда ыктыярчы болуп иштөө"),
    ("S", "Teach children how to play sports", "Учить детей спортивным играм", "Балдарга спорттук оюндарды үйрөтүү"),
    ("S", "Teach sign language to people who are deaf or hard of hearing", "Обучать жестовому языку людей с нарушениями слуха", "Угуусу начар адамдарга жаңдоо тилин үйрөтүү"),
    ("S", "Help conduct a group therapy session", "Помогать вести сеанс групповой терапии", "Топтук терапия сеансын өткөрүүгө жардам берүү"),
    ("S", "Take care of children at a day-care center", "Заботиться о детях в детском саду", "Бала бакчада балдарды кароо"),
    ("S", "Teach a high-school class", "Преподавать в старших классах школы", "Жогорку класстарда сабак берүү"),
    # Enterprising
    ("E", "Buy and sell stocks and bonds", "Покупать и продавать акции и облигации", "Акция жана облигацияларды сатып алуу жана сатуу"),
    ("E", "Manage a retail store", "Управлять розничным магазином", "Чекене дүкөндү башкаруу"),
    ("E", "Operate a beauty salon or barber shop", "Руководить салоном красоты или барбершопом", "Сулуулук салонун же барбершопту жетектөө"),
    ("E", "Manage a department within a large company", "Руководить отделом в крупной компании", "Чоң компанияда бөлүмдү жетектөө"),
    ("E", "Start your own business", "Открыть собственный бизнес", "Өз бизнесиңди ачуу"),
    ("E", "Negotiate business contracts", "Вести переговоры по бизнес-контрактам", "Бизнес-келишимдер боюнча сүйлөшүүлөрдү жүргүзүү"),
    ("E", "Represent a client in a lawsuit", "Представлять интересы клиента в суде", "Сотто кардардын кызыкчылыгын коргоо"),
    ("E", "Market a new line of clothing", "Продвигать новую линию одежды", "Кийимдин жаңы линиясын жарнамалоо"),
    ("E", "Sell merchandise at a department store", "Продавать товары в торговом центре", "Соода борборунда товар сатуу"),
    ("E", "Manage a clothing store", "Управлять магазином одежды", "Кийим дүкөнүн башкаруу"),
    # Conventional
    ("C", "Develop a spreadsheet using computer software", "Создавать электронные таблицы с расчётами", "Эсептөөлөрү бар электрондук таблицаларды түзүү"),
    ("C", "Proofread records or forms", "Проверять документы и формы на ошибки", "Документтерди жана формаларды катага текшерүү"),
    ("C", "Load computer software into a large computer network", "Устанавливать программы в большой компьютерной сети", "Чоң компьютердик тармакка программаларды орнотуу"),
    ("C", "Operate a calculator", "Выполнять расчёты на калькуляторе", "Калькулятор менен эсептөөлөрдү жүргүзүү"),
    ("C", "Keep shipping and receiving records", "Вести учёт отгрузок и поставок", "Жөнөтүү жана кабыл алуу эсебин жүргүзүү"),
    ("C", "Calculate the wages of employees", "Рассчитывать зарплату сотрудников", "Кызматкерлердин эмгек акысын эсептөө"),
    ("C", "Inventory supplies using a hand-held computer", "Проводить инвентаризацию с помощью терминала", "Терминал менен инвентаризация жүргүзүү"),
    ("C", "Record rent payments", "Вести учёт арендных платежей", "Ижара төлөмдөрүн каттоо"),
    ("C", "Keep inventory records", "Вести складской учёт", "Кампа эсебин жүргүзүү"),
    ("C", "Stamp, sort, and distribute mail for an organization", "Сортировать и распределять почту в организации", "Уюмда почтаны иргөө жана таратуу"),
]

ITEMS: List[dict] = [
    {"id": f"{t}{i % 10 + 1}", "type": t, "en": en, "ru": ru, "ky": ky}
    for i, (t, en, ru, ky) in enumerate(_RAW_ITEMS)
]
_ITEM_TYPE = {it["id"]: it["type"] for it in ITEMS}

# Presentation order: interleave R,I,A,S,E,C so same-type items don't cluster.
PRESENTATION = [ITEMS[r * 10 + i] for i in range(10) for r in range(6)]

# Ala-Too bachelor programs tagged with Holland codes (expert mapping based on
# O*NET occupation codes for typical target careers of each program).
PROGRAMS = [
    # Факультет инженерии и информатики
    {"ru": "Компьютерная инженерия", "en": "Computer Engineering", "ky": "Компьютердик инженерия", "fac_ru": "Факультет инженерии и информатики", "code": "IRC"},
    {"ru": "Кибербезопасность и этичный хакинг", "en": "Cybersecurity & Ethical Hacking", "ky": "Киберкоопсуздук жана этикалык хакинг", "fac_ru": "Факультет инженерии и информатики", "code": "IRE"},
    {"ru": "Основы креативных индустрий", "en": "Creative Industries", "ky": "Креативдик индустриялардын негиздери", "fac_ru": "Факультет инженерии и информатики", "code": "AEI"},
    {"ru": "Анализ данных и интеллектуальные системы", "en": "Data Analysis & Intelligent Systems", "ky": "Маалымат анализи жана интеллектуалдык системалар", "fac_ru": "Факультет инженерии и информатики", "code": "ICE"},
    {"ru": "Прикладная математика и информатика в образовании", "en": "Applied Math & CS in Education", "ky": "Билим берүүдөгү колдонмо математика жана информатика", "fac_ru": "Факультет инженерии и информатики", "code": "ISC"},
    {"ru": "Искусственный интеллект и робототехника", "en": "AI & Robotics", "ky": "Жасалма интеллект жана робототехника", "fac_ru": "Факультет инженерии и информатики", "code": "IRA"},
    {"ru": "Менеджмент качества в информационных технологиях", "en": "Quality Management in IT", "ky": "МТдагы сапат менеджменти", "fac_ru": "Факультет инженерии и информатики", "code": "CEI"},
    # Факультет экономики и управления
    {"ru": "Экономика (международная экономика и бизнес)", "en": "Economics (International Economics & Business)", "ky": "Экономика (эл аралык экономика жана бизнес)", "fac_ru": "Факультет экономики и управления", "code": "EIC"},
    {"ru": "Экономика (финансы и кредит)", "en": "Economics (Finance & Credit)", "ky": "Экономика (каржы жана кредит)", "fac_ru": "Факультет экономики и управления", "code": "ECI"},
    {"ru": "Экономика (международный бухгалтерский учёт и аудит)", "en": "Economics (International Accounting & Audit)", "ky": "Экономика (эл аралык бухгалтердик эсеп жана аудит)", "fac_ru": "Факультет экономики и управления", "code": "CEI"},
    {"ru": "Экономика (экономика окружающей среды)", "en": "Economics (Environmental Economics)", "ky": "Экономика (айлана-чөйрө экономикасы)", "fac_ru": "Факультет экономики и управления", "code": "IEC"},
    {"ru": "Менеджмент", "en": "Management", "ky": "Менеджмент", "fac_ru": "Факультет экономики и управления", "code": "ESC"},
    {"ru": "Менеджмент (индустрия гостеприимства и туризма)", "en": "Management (Hospitality & Tourism)", "ky": "Менеджмент (меймандостук жана туризм индустриясы)", "fac_ru": "Факультет экономики и управления", "code": "ESA"},
    {"ru": "Юриспруденция (международное и бизнес-право)", "en": "Law (International & Business Law)", "ky": "Юриспруденция (эл аралык жана бизнес укугу)", "fac_ru": "Факультет экономики и управления", "code": "EIS"},
    # Факультет гуманитарных наук
    {"ru": "Филология (английский язык и литература)", "en": "Philology (English Language & Literature)", "ky": "Филология (англис тили жана адабияты)", "fac_ru": "Факультет гуманитарных наук", "code": "AIS"},
    {"ru": "Филологическое образование", "en": "Philological Education", "ky": "Филологиялык билим берүү", "fac_ru": "Факультет гуманитарных наук", "code": "SAI"},
    {"ru": "Лингвистика (перевод и переводоведение)", "en": "Linguistics (Translation Studies)", "ky": "Лингвистика (котормо таануу)", "fac_ru": "Факультет гуманитарных наук", "code": "ASI"},
    {"ru": "Педагогика", "en": "Pedagogy", "ky": "Педагогика", "fac_ru": "Факультет гуманитарных наук", "code": "SAE"},
    {"ru": "Педагогика (STEM образование)", "en": "Pedagogy (STEM Education)", "ky": "Педагогика (STEM билим берүү)", "fac_ru": "Факультет гуманитарных наук", "code": "SIR"},
    {"ru": "Логопедия", "en": "Speech Therapy", "ky": "Логопедия", "fac_ru": "Факультет гуманитарных наук", "code": "SIA"},
    # Факультет социальных наук
    {"ru": "Международные отношения", "en": "International Relations", "ky": "Эл аралык мамилелер", "fac_ru": "Факультет социальных наук", "code": "ESA"},
    {"ru": "Психология", "en": "Psychology", "ky": "Психология", "fac_ru": "Факультет социальных наук", "code": "ISA"},
    {"ru": "Социальная психология", "en": "Social Psychology", "ky": "Социалдык психология", "fac_ru": "Факультет социальных наук", "code": "SIE"},
    {"ru": "Медиа, коммуникация и дизайн (журналистика)", "en": "Media, Communication & Design (Journalism)", "ky": "Медиа, коммуникация жана дизайн (журналистика)", "fac_ru": "Факультет социальных наук", "code": "AES"},
    {"ru": "Реклама и связи с общественностью", "en": "Advertising & Public Relations", "ky": "Жарнама жана коомчулук менен байланыш", "fac_ru": "Факультет социальных наук", "code": "EAS"},
    # Медицинский факультет
    {"ru": "Лечебное дело", "en": "General Medicine", "ky": "Дарылоо иши", "fac_ru": "Медицинский факультет", "code": "ISR"},
]


def questions(lang: str = "ru") -> List[dict]:
    lang = lang if lang in ("ru", "ky", "en") else "ru"
    return [{"id": it["id"], "text": it[lang]} for it in PRESENTATION]


def score(answers: Dict[str, int]) -> dict:
    """answers: {item_id: 1..5} for all 60 items -> scores, code, percents."""
    missing = [i for i in _ITEM_TYPE if i not in answers]
    if missing:
        raise ValueError(f"missing answers for {len(missing)} items")
    sums = {t: 0 for t in RIASEC_ORDER}
    for item_id, val in answers.items():
        t = _ITEM_TYPE.get(item_id)
        if t is None:
            raise ValueError(f"unknown item id: {item_id}")
        v = int(val)
        if not 1 <= v <= 5:
            raise ValueError(f"answer out of range for {item_id}: {val}")
        sums[t] += v
    # top-3 letters; ties broken by canonical RIASEC order
    ranked = sorted(RIASEC_ORDER, key=lambda t: (-sums[t], RIASEC_ORDER.index(t)))
    code = "".join(ranked[:3])
    percents = {t: round((sums[t] - 10) / 40 * 100) for t in RIASEC_ORDER}
    return {"scores": sums, "percents": percents, "code": code, "ranked": ranked}


def recommend(scores: Dict[str, int], lang: str = "ru", top_n: int = 6) -> List[dict]:
    """Rank programs by congruence with the user's normalized profile."""
    lang = lang if lang in ("ru", "ky", "en") else "ru"
    u = {t: (scores[t] - 10) / 40 for t in RIASEC_ORDER}  # 0..1
    out = []
    for p in PROGRAMS:
        w = [3, 2, 1]
        match = sum(wi * u[ch] for wi, ch in zip(w, p["code"])) / sum(w)
        out.append({
            "program": p[lang], "program_ru": p["ru"], "faculty": p["fac_ru"],
            "code": p["code"], "match": round(match * 100),
        })
    out.sort(key=lambda x: -x["match"])
    return out[:top_n]


def new_result_id() -> str:
    return uuid.uuid4().hex[:16]


def summary_for_llm(result: dict, name: str = None) -> str:
    """Compact Russian summary injected into the LLM context."""
    sc, pc = result["scores"], result["percents"]
    lines = []
    if name:
        lines.append(f"ФИО абитуриента: {name}")
    lines += [
        f"Код Голланда (топ-3 типа): {result['code']}",
        "Баллы по типам (10–50, в скобках % выраженности):",
    ]
    names = {t: TYPES[t]["ru"]["name"] for t in RIASEC_ORDER}
    for t in result["ranked"]:
        lines.append(f"- {t} ({names[t]}): {sc[t]} ({pc[t]}%)")
    recs = result.get("recommendations") or []
    if recs:
        lines.append("Рекомендованные программы Ала-Тоо (по соответствию профилю):")
        for r in recs:
            lines.append(f"- {r['program_ru']} — {r['faculty']} (код {r['code']}, соответствие {r['match']}%)")
    return "\n".join(lines)
