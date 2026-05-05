"""Generate outputs/final_research_report.html from a batch run folder (CSV + metrics_dictionary + PNG figures as base64 data URIs)."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
from collections import defaultdict
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from transcriptions_analysis.content_category import KEYWORDS, PRIMARY_TIE_BREAK_ORDER
OUT = REPO / "outputs"
DEFAULT_FINAL_HTML = OUT / "final_research_report.html"

DAY_METRICS = [
    "content_category_confidence",
    "content_file_basename_token_count",
    "content_script_arabic_ratio",
    "content_script_cjk_ratio",
    "content_script_cyrillic_ratio",
    "content_script_digit_ratio",
    "content_script_latin_ratio",
    "content_script_other_ratio",
    "layer_a_distinct_speakers",
    "layer_a_duplicate_adjacent_segment_ratio",
    "layer_a_malformed_timestamp_ratio",
    "layer_a_max_words_per_segment",
    "layer_a_median_chars_per_segment",
    "layer_a_median_words_per_segment",
    "layer_a_segment_count",
    "layer_a_separator_count",
    "layer_a_speaker_switch_count",
    "layer_a_speaker_switch_rate",
    "layer_a_unreasonable_speaker_churn",
    "layer_b_control_char_count",
    "layer_b_hapax_ratio",
    "layer_b_language_mixed",
    "layer_b_long_word_ratio",
    "layer_b_mean_word_length",
    "layer_b_median_word_length",
    "layer_b_nonprintable_ratio",
    "layer_b_primary_language_confidence",
    "layer_b_repeated_char_run_ratio",
    "layer_b_short_utterance_ratio",
    "layer_b_total_tokens",
    "layer_b_type_token_ratio",
    "layer_b_unicode_replacement_count",
    "layer_b_unique_tokens",
    "layer_b_word_entropy_bits",
    "layer_b_zero_width_count",
]

# Короткие заголовки и пояснения для подписей к рисункам (без повторения про «ведро по дням»).
METRIC_FRIENDLY: dict[str, tuple[str, str]] = {
    "content_category_confidence": (
        "Насколько выигравшая категория доминирует над альтернативами",
        "Отношение силы выбранной основной метки ко второй по силе среди кандидатов (или шкала при отсутствии конкурента). "
        "Согласовано с выбором primary по покрытию словаря / структуре диалога; не вероятность класса и не softmax.",
    ),
    "content_file_basename_token_count": (
        "Сложность имени файла",
        "Сколько «кусков» в имени исходного аудиофайла — косвенный признак того, насколько осмысленно названо входное сообщение.",
    ),
    "content_script_arabic_ratio": (
        "Доля арабской письменности",
        "Какая часть букв и цифр в тексте относится к арабскому алфавиту; помогает видеть всплески арабоязычного материала.",
    ),
    "content_script_cjk_ratio": (
        "Доля китайского, японского, корейского",
        "Доля символов CJK/хангыля среди букв и цифр — маркер восточноазиатского текста в выборке.",
    ),
    "content_script_cyrillic_ratio": (
        "Доля кириллицы",
        "Насколько текст после распознавания опирается на кириллицу; полезно рядом с языковой смесью.",
    ),
    "content_script_digit_ratio": (
        "Доля цифр",
        "Сколько из буквенно-цифрового текста составляют цифры — всплески типичны для кодов, таблиц, номеров.",
    ),
    "content_script_latin_ratio": (
        "Доля латиницы",
        "Доля латинских букв среди букв и цифр; растёт при коде, брендах, англицизмах и смешанных текстах.",
    ),
    "content_script_other_ratio": (
        "Доля прочих алфавитов",
        "Всё, что не попало в основные скрипты; высокие значения стоит проверять на артефакты разметки.",
    ),
    "layer_a_distinct_speakers": (
        "Число разных спикеров",
        "Сколько разных меток говорящего встретилось в одной транскрипции — от монолога до большого совещания.",
    ),
    "layer_a_duplicate_adjacent_segment_ratio": (
        "Повторы подряд идущих реплик",
        "Доля пар соседних сегментов с одинаковым текстом; может указывать на задвоение ASR или копипаст в источнике.",
    ),
    "layer_a_malformed_timestamp_ratio": (
        "Проблемы с метками времени",
        "Доля реплик со спикером, у которых нет корректной пары «начало — конец» в скобках. Низко — разметка времени в основном аккуратная.",
    ),
    "layer_a_max_words_per_segment": (
        "Самая длинная реплика (в словах)",
        "Максимум слов в одном сегменте; выбросы показывают очень длинные монологические куски.",
    ),
    "layer_a_median_chars_per_segment": (
        "Типичная длина реплики в символах",
        "Медианная длина тела сегмента в символах — грубый масштаб «плотности» высказывания.",
    ),
    "layer_a_median_words_per_segment": (
        "Типичная длина реплики в словах",
        "Медианное число слов в одной реплике; вместе с числом сегментов описывает стиль: короткие обмены или развёрнутые фразы.",
    ),
    "layer_a_segment_count": (
        "Сколько сегментов в записи",
        "Число выделенных реплик после разбора диаризации; высокое значение — диалог с большим числом реплик.",
    ),
    "layer_a_separator_count": (
        "Разделители между блоками",
        "Сколько длинных «линий-разделителей» между частями текста; отражает структуру экспорта.",
    ),
    "layer_a_speaker_switch_count": (
        "Сколько раз сменился спикер",
        "Абсолютное число переключений между говорящими; растёт на живых дискуссиях.",
    ),
    "layer_a_speaker_switch_rate": (
        "Частота смены спикера",
        "Число смен делится на число сегментов: насколько «рваный» диалог относительно его длины.",
    ),
    "layer_a_unreasonable_speaker_churn": (
        "Подозрительно частые смены спикера",
        "Эвристика «слишком много переключений на мало текста» — флаг проверить качество диаризации или шум.",
    ),
    "layer_b_control_char_count": (
        "Служебные управляющие символы",
        "Счётчик редких управляющих символов в тексте; всплески могут идти от копирования из терминала или битой кодировки.",
    ),
    "layer_b_hapax_ratio": (
        "Слова, встретившиеся один раз",
        "Доля позиций токенов, которые встречаются ровно один раз; высоко на узкоспециальных или шумных текстах.",
    ),
    "layer_b_language_mixed": (
        "Признак смешения языков",
        "Насколько детектор языка видит несколько языков или неуверенный топ-2 в одной записи.",
    ),
    "layer_b_long_word_ratio": (
        "Доля длинных слов",
        "Доля токенов длиной от 7 символов — часто техника, идентификаторы, составные термины.",
    ),
    "layer_b_mean_word_length": (
        "Средняя длина слова",
        "Среднее число символов в токене; вместе с тематикой помогает отличать «технический» сленг от бытовой речи.",
    ),
    "layer_b_median_word_length": (
        "Медианная длина слова",
        "Типичная длина токена; устойчивее к выбросам, чем среднее.",
    ),
    "layer_b_nonprintable_ratio": (
        "Непечатаемые символы",
        "Доля символов вне обычной печати; рост — повод проверить цепочку экспорта и очистку текста.",
    ),
    "layer_b_primary_language_confidence": (
        "Уверенность в основном языке",
        "Насколько уверенно определён главный язык записи по выдержкам из начала, середины и конца текста.",
    ),
    "layer_b_repeated_char_run_ratio": (
        "Заёмы одного символа подряд",
        "Доля буквенно-цифровых символов в повторах одного знака длиной не меньше трёх (например смещённые повторы букв или тире).",
    ),
    "layer_b_short_utterance_ratio": (
        "Очень короткие реплики",
        "Доля сегментов из одного–двух слов — характерно для чатовых «ок», подтверждений и шума.",
    ),
    "layer_b_total_tokens": (
        "Объём текста в словах",
        "Суммарное число токенов по пробелам — масштаб «сколько сказано» в одной транскрипции.",
    ),
    "layer_b_type_token_ratio": (
        "Разнообразие словаря (TTR)",
        "Отношение уникальных слов к общему числу: выше — богаче лексика при том же объёме.",
    ),
    "layer_b_unicode_replacement_count": (
        "Символы замены при ошибке декодирования",
        "Счётчик специального знака «вопрос в ромбе», который появляется, когда байты не удалось корректно прочитать как текст; ненулевые значения — сигнал проверить кодировку или цепочку экспорта.",
    ),
    "layer_b_unique_tokens": (
        "Число уникальных слов",
        "Сколько различных токенов в записи; растёт с длиной и разнообразием темы.",
    ),
    "layer_b_word_entropy_bits": (
        "Энтропия слов",
        "Насколько «размазано» распределение слов: выше — меньше повторов одних и тех же слов внутри записи.",
    ),
    "layer_b_zero_width_count": (
        "Невидимые и нулевой ширины символы",
        "Счётчик нулевой ширины и похожих символов; полезно для контроля «грязного» ввода из мессенджеров.",
    ),
}

CATEGORY_LABEL_RU: dict[str, str] = {
    "business_work": "Бизнес и работа",
    "tech_it": "IT и технологии",
    "general_monologue": "Монолог / размышления",
    "dialogue_meeting": "Диалоги и совещания",
    "quick_message": "Короткие сообщения",
    "finance_legal": "Финансы и право",
    "media_creative": "Медиа и творчество",
    "short_note": "Короткие заметки",
    "education": "Обучение",
    "personal": "Личное",
    "support": "Поддержка и сервис",
    "empty": "Пусто / без класса",
    "unknown": "Не классифицировано",
}

# Краткое назначение словарных категорий (для блока методологии; синхронизировать смысл с KEYWORDS в коде).
CATEGORY_PURPOSE: dict[str, str] = {
    "business_work": (
        "Деловая и офисная коммуникация: проекты, клиенты, встречи и созвоны, договоры, продажи, маркетинг, команда."
    ),
    "tech_it": (
        "Инженерные и IT-темы: разработка, инфраструктура, ошибки и отладка, API, данные, модели, LLM, развёртывание."
    ),
    "education": ("Учёба и формальное обучение: школа, вуз, курсы, экзамены, лекции."),
    "personal": ("Личная жизнь и быт: семья, друзья, дом, здоровье, поездки, отношения."),
    "media_creative": ("Медиа и творчество: музыка, видео, подкасты, сценарии, площадки вроде YouTube."),
    "finance_legal": ("Финансы и право: оплаты, счета, налоги, кредиты, банк, юридические формулировки."),
    "support": ("Помощь и сопровождение: настройка, инструкции, устранение проблем, обращения в поддержку."),
}


def lang_label(code: str) -> str:
    m = {
        "en": "Английский",
        "ru": "Русский",
        "uk": "Украинский",
        "de": "Немецкий",
        "pl": "Польский",
        "be": "Белорусский",
        "(null)": "Язык не определён",
    }
    return m.get(code, code)


def category_label(code: str) -> str:
    return CATEGORY_LABEL_RU.get(code, code.replace("_", " "))


def build_content_category_methodology_html() -> str:
    """Подробный блок методологии определения типа контента (синхронизирован с content_category.py)."""
    kw_rows: list[str] = []
    for cat, stems in KEYWORDS.items():
        purpose = CATEGORY_PURPOSE.get(cat, "")
        stem_cell = ", ".join(f"<code>{escape(s)}</code>" for s in stems)
        kw_rows.append(
            "<tr>"
            f'<td class="border p-2 align-top font-medium">{escape(category_label(cat))}</td>'
            f'<td class="border p-2 align-top text-zinc-700">{escape(purpose)}</td>'
            f'<td class="border p-2 align-top text-xs font-mono leading-snug">{stem_cell}</td>'
            "</tr>"
        )
    kw_table_body = "\n".join(kw_rows)

    prio_items = " → ".join(escape(category_label(c)) for c in PRIMARY_TIE_BREAK_ORDER)

    return f"""
    <section class="mb-10 border-t pt-10 mt-10 text-sm leading-relaxed text-zinc-800">
      <h2 class="text-2xl font-semibold text-zinc-900 mb-4">Методология: как определяется тип контента</h2>
      <p class="mb-4">Ниже описано, <strong>как именно</strong> каждой транскрипции присваивается поле основного типа контента
        и связанные с ним метки. Это <strong>не нейросетевая тематическая модель</strong> и не семантический поиск:
        используется детерминированный набор правил по тексту после разбора диаризации и по структуре реплик.</p>

      <h3 class="text-lg font-semibold text-zinc-900 mt-6 mb-2">1. Подготовка текста</h3>
      <ul class="list-disc pl-5 space-y-2 mb-4">
        <li>Из сегментов диаризации берётся только <strong>тело реплик</strong> (без меток спикеров и без временных меток в скобках и inline-формате).</li>
        <li>Текст приводится к нижнему регистру; перед поиском по словарю удаляются типичные «паразитные» вставки
          (например служебные пометки вроде <code>[noise]</code> и отдельные междометия по шаблонам).</li>
        <li>Для порогов «длины без словаря» считаются <strong>токены</strong>: последовательности букв/цифр длиной не меньше трёх символов
          (кириллица, латиница, цифры, дефис и апостроф внутри слова).</li>
      </ul>

      <h3 class="text-lg font-semibold text-zinc-900 mt-6 mb-2">2. Словарные категории (мультиметки)</h3>
      <p class="mb-3">По очищенному тексту выполняется поиск по словарю: для <strong>каждого элемента списка</strong> строится шаблон
        с границами слова Unicode (<code>\\b</code> вокруг экранированной подстроки), чтобы не ловить случайные вхождения внутри других слов
        (например «код» в «кодекс»). Элементы списка часто заданы как короткие корни («задач», «встреч»), чтобы одно правило покрывало несколько словоформ,
        если эта форма встречается отдельным токеном. Если по категории найдено хотя бы одно совпадение, категория попадает в список сработавших;
        счётчик категории увеличивается на число <strong>разных</strong> сработавших элементов её списка.</p>
      <div class="overflow-x-auto mb-4">
        <table class="w-full text-xs border-collapse border border-zinc-200">
          <thead>
            <tr class="bg-zinc-100">
              <th class="border p-2 text-left w-40">Категория в отчёте</th>
              <th class="border p-2 text-left">Что обозначает (смысл)</th>
              <th class="border p-2 text-left">Ключевые подстроки в текущей версии правил</th>
            </tr>
          </thead>
          <tbody>
            {kw_table_body}
          </tbody>
        </table>
      </div>
      <p class="text-xs text-zinc-600">Список подстрок задаётся в коде модуля классификации; при обновлении словаря меняется и состав триггеров.
        Подстроки на русском и английском отражают ожидаемую лексику выборки, а не полное покрытие языка.</p>

      <h3 class="text-lg font-semibold text-zinc-900 mt-6 mb-2">3. Структурная категория «Диалоги и совещания»</h3>
      <p class="mb-2">Отдельно вычисляется, похожа ли запись на <strong>диалог</strong>:</p>
      <ul class="list-disc pl-5 space-y-2 mb-3">
        <li>либо в транскрипции не меньше <strong>двух различных</strong> меток говорящего;</li>
        <li>либо число <strong>смен спикера</strong> между соседними сегментами (где у обоих задан спикер) строго больше <strong>трёх</strong>.</li>
      </ul>
      <p class="mb-4">Если диалог признан, но при этом <strong>не</strong> сработали словарные метки «Бизнес и работа» и «Поддержка и сервис»,
        в список меток добавляется «Диалоги и совещания». В словаре <code>category_scores</code> для прозрачности хранится целое значение
        <code>число_уникальных_спикеров + 2 × число_смен_спикера</code>; для <strong>сравнения кандидатов на основную категорию</strong> структура переводится
        в дробь 0..1 через логарифмическую нормализацию, чтобы сопоставимость с «покрытием словаря» была честнее.</p>

      <h3 class="text-lg font-semibold text-zinc-900 mt-6 mb-2">4. Как выбирается одна «основная» категория (обновлённая логика)</h3>
      <p class="mb-2">Для каждой словарной категории с ненулевыми попаданиями считается <strong>покрытие словаря</strong>:
        <code>hits / число_элементов_списка_ключей</code> (доля сработавших уникальных подстрок от размера словаря категории, не больше 1).
        Так устраняется смещение в пользу категорий с длинным списком ключей при сравнении «насколько текст подтверждает метку».</p>
      <p class="mb-2">«Диалоги и совещания» участвуют в выборе основной метки <strong>только если лексический сигнал слабый</strong>: максимальное покрытие по любой словарной
        категории ниже ~12% <strong>и</strong> ни в одной словарной категории нет больше двух сработавших подстрок. Иначе основная выбирается только среди словарных меток —
        чтобы одно случайное IT-слово не «перебивало» настоящее совещание с богатой бизнес-лексикой.</p>
      <p class="mb-2">Среди допущенных кандидатов выбирается категория с <strong>наибольшей силой</strong> (покрытие словаря или нормализованная структура диалога).
        При равенстве силы действует фиксированный порядок «разрыва ничьей» (продуктовая политика, не вероятность):</p>
      <p class="mb-3 font-mono text-xs bg-zinc-50 border rounded p-3">{prio_items}</p>
      <p class="mb-4">Если словарных попаданий не было, но структура диалога добавила метку, основной становится «Диалоги и совещания». Если не сработало ничего —
        используется запасной сценарий по длине текста (следующий раздел).</p>

      <h3 class="text-lg font-semibold text-zinc-900 mt-6 mb-2">5. Если словарь ничего не поймал</h3>
      <p class="mb-2">Если ни одна словарная и структурная (диалоговая) метка не сработала, основной тип назначается <strong>только по числу токенов</strong>:</p>
      <ul class="list-disc pl-5 space-y-2 mb-4">
        <li><strong>{escape(category_label("short_note"))}</strong> — меньше 15 токенов;</li>
        <li><strong>{escape(category_label("quick_message"))}</strong> — от 15 до 59 токенов включительно;</li>
        <li><strong>{escape(category_label("general_monologue"))}</strong> — 60 токенов и больше.</li>
      </ul>
      <p class="mb-4">В этом случае внутреннему счётчику присваивается фиксированное значение для расчёта вспомогательной метрики «плотности сигнала»
        (см. раздел про показатель уверенности на графике).</p>

      <h3 class="text-lg font-semibold text-zinc-900 mt-6 mb-2">6. Пустые записи и «не классифицировано»</h3>
      <ul class="list-disc pl-5 space-y-2 mb-4">
        <li><strong>{escape(category_label("empty"))}</strong> — нет сегментов или после очистки не осталось значимого текста в классификаторе.</li>
        <li><strong>{escape(category_label("unknown"))}</strong> — служебное значение слоя B, если транскрипция на входе отсутствует или пуста
          до расчёта признаков; такие строки не проходят полный сценарий классификации по словарю.</li>
      </ul>

      <h3 class="text-lg font-semibold text-zinc-900 mt-6 mb-2">7. Показатель «уверенность» (на графиках)</h3>
      <p class="mb-4">Число 0–1 — это <strong>не вероятность правильного класса</strong>. Оно отражает <strong>доминирование</strong> выигравшей метки:
        отношение её силы ко второй по величине среди кандидатов (если второй нет — масштабирование по фиксированной шкале). Так значение становится согласованным
        с тем, как выбрана основная категория, а не «плотностью суммы счётчиков к длине текста».</p>

      <h3 class="text-lg font-semibold text-zinc-900 mt-6 mb-2">8. На что не претендует классификация</h3>
      <ul class="list-disc pl-5 space-y-2">
        <li>Это не разметка «истинной темы» и не жанр контента в редакционном смысле — только устойчивые лексические и простые структурные признаки.</li>
        <li>Сдвиг долей по месяцам отражает в том числе <strong>смену лексики и длины записей</strong>, а не обязательно изменение качества распознавания речи.</li>
        <li>Для редких доменов и жаргона, не попавшего в словарь, запись может уйти в запасные классы по длине или в диалог без бизнес-триггеров.</li>
        <li>При сравнении периодов имеет смысл смотреть на объём выборки в интервале и на доли языков — они влияют на лексику независимо от классификатора.</li>
      </ul>
    </section>
    """


def hsl_colors(n: int) -> list[str]:
    out: list[str] = []
    for i in range(n):
        h = (i * 360 / max(n, 1)) % 360
        out.append(f"hsl({h:.0f} 58% 52%)")
    return out


def aggregate_categories(path: Path) -> tuple[dict[str, int], int]:
    cat: dict[str, int] = defaultdict(int)
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat[row["_category"]] += int(row["n_in_category"])
    return dict(cat), sum(cat.values())


def aggregate_languages(path: Path) -> tuple[dict[str, int], int]:
    lang: dict[str, int] = defaultdict(int)
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lang[row["_category"]] += int(row["n_in_category"])
    return dict(lang), sum(lang.values())


def sorted_month_keys_from_share(path: Path) -> list[str]:
    months: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            months.add(row["bucket_month"])
    return sorted(months)


def pivot_monthly_shares(
    path: Path,
    item_order: list[str],
    months: list[str],
) -> dict[str, list[float]]:
    """For each item, list of percentage (0-100) per month in order `months`."""
    per_month: dict[str, dict[str, float]] = defaultdict(dict)
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            m = row["bucket_month"]
            key = row["_category"]
            per_month[m][key] = float(row["share"]) * 100.0
    out: dict[str, list[float]] = {}
    for key in item_order:
        out[key] = [round(per_month[m].get(key, 0.0), 2) for m in months]
    return out


def month_labels_ru(months: list[str]) -> list[str]:
    ru = {
        "01": "Янв",
        "02": "Фев",
        "03": "Мар",
        "04": "Апр",
        "05": "Май",
        "06": "Июн",
        "07": "Июл",
        "08": "Авг",
        "09": "Сен",
        "10": "Окт",
        "11": "Ноя",
        "12": "Дек",
    }
    out: list[str] = []
    for m in months:
        y, mo, *_ = m.split("-")
        out.append(f"{ru[mo]} {y}")
    return out


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _finite_values(series: list[float]) -> list[float]:
    return [x for x in series if x == x]


def time_agg_month_metrics_by_month(path: Path, months: list[str]) -> dict[str, list[float]]:
    """Read selected median columns from ``time_agg_month.csv`` aligned to ``months`` order."""
    keys = (
        "layer_a_segment_count_median",
        "layer_a_median_words_per_segment_median",
        "layer_a_malformed_timestamp_ratio_median",
    )
    empty = {k: [] for k in keys}
    if not path.is_file():
        return empty
    by_month: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_month[row["bucket_month"]] = row
    out: dict[str, list[float]] = {}
    for k in keys:
        series: list[float] = []
        for m in months:
            r = by_month.get(m)
            if r is None:
                series.append(float("nan"))
                continue
            raw = r.get(k)
            if raw is None or raw == "":
                series.append(float("nan"))
            else:
                series.append(float(raw))
        out[k] = series
    return out


def build_dynamics_conclusions_li_html(
    *,
    months: list[str],
    month_labels: list[str],
    cats: dict[str, int],
    total: int,
    cat_matrix: dict[str, list[float]],
    langs: dict[str, int],
    lang_total: int,
    lang_matrix: dict[str, list[float]],
    lang_order: list[str],
    n_month: list[int],
    time_agg_month_csv: Path,
) -> str:
    """Build ``<li>…</li>`` bullets for «Выводы по динамике» from this run's aggregates."""
    items: list[str] = []

    # --- Content mix ---
    top3 = sorted(cats.items(), key=lambda x: -x[1])[:3]
    top3_txt = ", ".join(
        f"{escape(category_label(k))} ({round(100 * v / total, 1)}%)" for k, v in top3
    )
    n_m = len(months)
    if n_m >= 2:
        ranked_spans: list[tuple[str, float, float, float]] = []
        for cat, n in cats.items():
            if cat not in cat_matrix or n / total < 0.02:
                continue
            row = cat_matrix[cat]
            lo, hi = min(row), max(row)
            span = hi - lo
            ranked_spans.append((cat, span, lo, hi))
        ranked_spans.sort(key=lambda x: -x[1])
        swing_chunks: list[str] = []
        for cat, span, lo, hi in ranked_spans[:3]:
            if span < 2.5:
                continue
            swing_chunks.append(
                f"{escape(category_label(cat))}: {lo:.1f}–{hi:.1f}% "
                f"(размах {span:.1f} п.п.)"
            )
        swing_txt = (
            "Наиболее заметные колебания месячных долей: "
            + "; ".join(swing_chunks)
            + "."
            if swing_chunks
            else "Месячные доли при крупных категориях меняются умеренно относительно их базового веса."
        )
    else:
        swing_txt = "Сравнение «месяц к месяцу» по долям здесь ограничено: в разбивке фактически один календарный месяц."

    items.append(
        "<li><strong>Состав контента.</strong> На всей выборке крупнейшие группы: "
        f"{top3_txt}. {swing_txt} Это в первую очередь сигнал о "
        "<em>смене того, что пользователи приносят на транскрипцию</em>, а не автоматически "
        "о деградации модели распознавания.</li>"
    )

    # --- Language ---
    ru_share_overall = round(100 * langs.get("ru", 0) / lang_total, 1) if lang_total else 0.0
    lang_bits: list[str] = [f"Русский язык суммарно около {ru_share_overall}% записей."]
    if "ru" in lang_matrix and n_m >= 2:
        rr = lang_matrix["ru"]
        lang_bits.append(
            f"По месяцам доля русского колеблется примерно от {min(rr):.1f}% до {max(rr):.1f}%."
        )
    best_code: str | None = None
    best_span = 0.0
    best_hi = 0.0
    for code in lang_order:
        if code in ("ru",):
            continue
        if not lang_total or langs.get(code, 0) / lang_total < 0.005:
            continue
        row = lang_matrix.get(code)
        if not row or len(row) < 2:
            continue
        span = max(row) - min(row)
        if span > best_span or (span == best_span and langs.get(code, 0) > langs.get(best_code or "", 0)):
            best_span = span
            best_code = code
            best_hi = max(row)
    if best_code and best_span >= 0.8:
        lang_bits.append(
            f"У {escape(lang_label(best_code))} виден месячный размах порядка {best_span:.1f} п.п. "
            f"(пиковая доля до {best_hi:.1f}%): при сравнении лексических метрик стоит помнить про эту смесь."
        )
    else:
        lang_bits.append(
            "Доли прочих языков малы, но по месяцам не полностью плоские — это полезно учитывать рядом с текстовыми показателями."
        )
    items.append(
        "<li><strong>Язык.</strong> "
        + " ".join(lang_bits)
        + "</li>"
    )

    # --- Dialogue structure (Layer A medians by month) ---
    ta = time_agg_month_metrics_by_month(time_agg_month_csv, months)
    seg = _finite_values(ta.get("layer_a_segment_count_median", []))
    words = _finite_values(ta.get("layer_a_median_words_per_segment_median", []))
    if seg and words:
        items.append(
            "<li><strong>Структура диалога.</strong> По месячным медианам: число сегментов на транскрипцию "
            f"колеблется от {min(seg):.0f} до {max(seg):.0f}, медиана слов на сегмент — "
            f"примерно от {min(words):.0f} до {max(words):.0f}. Такие сдвиги смешивают короткие сообщения "
            "и длинные обсуждения и сами двигают текстовые метрики, даже при стабильном распознавании.</li>"
        )
    else:
        items.append(
            "<li><strong>Структура диалога.</strong> Месячные медианы сегментов и длины реплики в этом прогоне "
            "не удалось согласовать с <code>time_agg_month.csv</code> — опирайтесь на графики ниже.</li>"
        )

    # --- Malformed timestamps ---
    mal = _finite_values(ta.get("layer_a_malformed_timestamp_ratio_median", []))
    if mal and max(mal) < 1e-9:
        mal_txt = (
            "Медиана доли некорректных временных меток по месяцам остаётся на нуле (в пределах численной точности); "
            "всплески на дневных графиках смотрите вместе со столбцом объёма за тот день."
        )
    elif mal:
        mal_txt = (
            f"Медиана доли некорректных меток по месяцам остаётся низкой (порядка {min(mal):.4f}–{max(mal):.4f}); "
            "дневные всплески интерпретируйте вместе с числом записей за день."
        )
    else:
        mal_txt = (
            "Для месячной сводки по доле некорректных меток нет числового ряда — ориентируйтесь на дневные графики ниже."
        )
    items.append(f"<li><strong>Разметка времени.</strong> {mal_txt}</li>")

    # --- Mix / volume ---
    if n_month:
        i_thin = min(range(len(n_month)), key=lambda j: n_month[j])
        thin_label = escape(month_labels[i_thin])
        thin_n = n_month[i_thin]
        items.append(
            "<li><strong>Контроль смеси и объёма.</strong> Самый «узкий» месяц по числу записей — "
            f"<strong>{thin_label}</strong> ({thin_n:,} шт.); там месячные доли и дневные точки менее устойчивы. "
            "Имеет смысл сопоставлять тип контента с форматом исходного файла (голосовые против длинных записей совещаний), "
            "если в продукте есть гипотезы про разные воронки.</li>"
        )
    else:
        items.append(
            "<li><strong>Контроль смеси.</strong> Имеет смысл сопоставлять тип контента с форматом исходного файла "
            "(например, голосовые против длинных записей совещаний), если в продукте есть гипотезы про разные воронки.</li>"
        )

    return "\n        ".join(items)


def _dynamics_narrative_body_60fdd05a_html() -> str:
    """Развёрнутые выводы по прогону 60fdd05a (авторский разбор; цифры зафиксированы под этот каталог outputs/)."""
    return """
    <div class="space-y-4 text-slate-800 text-[15px] leading-relaxed">
      <p class="text-xs text-slate-500 border-l-2 border-slate-300 pl-3">Ниже — развёрнутый разбор именно для прогона
        <code>60fdd05a-c3c3-405e-936d-0d0e70cb21a0</code> (агрегаты в <code>outputs/…/manifest.json</code> и месячных CSV).
        Ниже — только аналитические выводы по данным, без описания методики.</p>

      <h3 class="text-base font-semibold text-slate-900">Ключевые итоги по структуре корпуса</h3>
      <p>В выборке <strong>16&nbsp;544</strong> записи за период <strong>авг&nbsp;2025 — апр&nbsp;2026</strong>. Ядро корпуса устойчиво:
        суммарно лидируют <strong>бизнес и работа</strong> (~21%), <strong>диалоги и совещания</strong> (~18%) и
        <strong>монолог / размышления</strong> (~16%). Вместе это более половины всех транскрипций, то есть основной
        поток — рабочие и коммуникационные сценарии, а не развлекательные или узкоспециализированные ниши.</p>

      <h3 class="text-base font-semibold text-slate-900 pt-1">Три режима динамики в контенте</h3>
      <p><strong>Режим 1 (сентябрь–октябрь 2025):</strong> бизнес-доминирование. Пик доли бизнеса — почти <strong>30%</strong>
        в октябре при снижении диалогов до ~<strong>12%</strong>. Это выглядит как период более «формализованных» рабочих
        записей.</p>
      <p><strong>Режим 2 (декабрь 2025 — февраль 2026):</strong> разворот к коммуникационному формату. В январе
        фиксируется максимум по доле <strong>диалогов и совещаний</strong> (~<strong>25%</strong>) при одновременном
        минимуме бизнеса (~<strong>14%</strong>) и росте <strong>quick_message</strong>/<strong>short_note</strong>.
        По сути, центр тяжести смещается от «длинных деловых блоков» к более коротким обменам.</p>
      <p><strong>Режим 3 (март–апрель 2026):</strong> частичная нормализация. Бизнес возвращается в коридор ~<strong>21%</strong>,
        диалоги снижаются к ~<strong>16–17%</strong>, монологи стабилизируются около <strong>16–18%</strong>. Это уже не
        экстремумы октября/января, а более сбалансированная смесь.</p>

      <h3 class="text-base font-semibold text-slate-900 pt-1">Нестандартные и «тихие» сигналы</h3>
      <p><strong>IT и технологии</strong> остаются низкими во все месяцы (обычно ~<strong>1–2%</strong>, максимум ~3.1% в ноябре),
        поэтому для этого корпуса IT — маргинальный первичный класс. Рост в ноябре визуально заметен, но месяц имеет
        малый объём (<strong>816</strong> записей), значит это скорее локальный всплеск, чем тренд уровня всей системы.</p>
      <p><strong>Медиа и творчество</strong> и <strong>support</strong> держатся в среднем диапазоне (~7–12% и ~5–10% соответственно),
        но без монотонного тренда: это «фоновые» категории, которые меняются вместе с общим режимом месяца, а не задают его.</p>

      <h3 class="text-base font-semibold text-slate-900 pt-1">Языковая динамика как объясняющий фактор</h3>
      <p>Русский остаётся доминирующим, но его доля снижается от ~<strong>99%</strong> в локальных пиках к ~<strong>88.8%</strong>
        в апреле 2026. На этом фоне английский растёт до ~<strong>10.2%</strong> (апрель). Это отдельный сдвиг состава входа:
        часть колебаний текстовых метрик в конце периода с высокой вероятностью объясняется изменением языковой смеси, а не
        только внутренними изменениями качества транскрипции.</p>

      <h3 class="text-base font-semibold text-slate-900 pt-1">Что это значит для интерпретации качества</h3>
      <p>Главный вывод по этому прогону: ряд показывает не «один стабильный тип данных», а <strong>смену профилей использования</strong>.
        Поэтому сравнение качества между месяцами корректно делать только с учётом режима месяца (бизнесовый, диалоговый, смешанный)
        и языковой композиции; без этой стратификации легко принять сдвиг входного потока за деградацию/улучшение модели.</p>
    </div>
    """.strip()


def resolve_dynamics_body_html(
    run_id: str,
    *,
    months: list[str],
    month_labels: list[str],
    cats: dict[str, int],
    total: int,
    cat_matrix: dict[str, list[float]],
    langs: dict[str, int],
    lang_total: int,
    lang_matrix: dict[str, list[float]],
    lang_order: list[str],
    n_month: list[int],
    time_agg_month_csv: Path,
) -> str:
    """Тело блока «Выводы по динамике»: развёрнутый разбор для известных прогонов, иначе краткая числовая сводка."""
    if run_id == "60fdd05a-c3c3-405e-936d-0d0e70cb21a0":
        return _dynamics_narrative_body_60fdd05a_html()
    procedural = build_dynamics_conclusions_li_html(
        months=months,
        month_labels=month_labels,
        cats=cats,
        total=total,
        cat_matrix=cat_matrix,
        langs=langs,
        lang_total=lang_total,
        lang_matrix=lang_matrix,
        lang_order=lang_order,
        n_month=n_month,
        time_agg_month_csv=time_agg_month_csv,
    )
    return (
        '<p class="text-xs text-slate-500 mb-3">Краткая автосводка по таблицам этого прогона '
        "(месячные доли, <code>time_agg_month.csv</code>); для развёрнутой интерпретации под конкретный прогон "
        "можно заменить блок в коде аналогично зафиксированному разбору.</p>"
        f'<ul class="space-y-3 text-slate-800 list-disc pl-5">\n        {procedural}\n      </ul>'
    )


def _png_data_uri(path: Path) -> str:
    """Encode a PNG on disk as a data URI for self-contained HTML."""
    if not path.is_file():
        print(f"error: нет файла рисунка для встраивания в отчёт: {path}", file=sys.stderr)
        raise SystemExit(1)
    try:
        raw = path.read_bytes()
    except OSError as e:
        print(f"error: не удалось прочитать {path}: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def main(run_id: str, *, output_html: Path | None = None) -> None:
    """Build ``final_research_report.html`` (or ``output_html``) from ``outputs/<run_id>/`` CSV + manifest + figures."""
    run_dir = (OUT / run_id).resolve()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        print(
            f"error: нет папки прогона или manifest.json: {manifest_path}\n"
            f"  Укажите UUID каталога в outputs/, например: python scripts/build_final_research_report.py --run-id <uuid>",
            file=sys.stderr,
        )
        raise SystemExit(1)

    manifest = read_manifest(manifest_path)
    run_id_display = manifest.get("run_id", run_id)

    cat_csv = run_dir / "content_category_share_time_agg_month.csv"
    lang_csv = run_dir / "language_share_time_agg_month.csv"
    cats, total = aggregate_categories(cat_csv)
    langs, lang_total = aggregate_languages(lang_csv)

    months = sorted_month_keys_from_share(cat_csv)
    labels = month_labels_ru(months)

    cat_order = sorted(cats.keys(), key=lambda c: (-cats[c], c))
    lang_order = sorted(langs.keys(), key=lambda c: (-langs[c], c))

    n_month: list[int] = []
    with cat_csv.open(encoding="utf-8") as f:
        seen: dict[str, int] = {}
        for row in csv.DictReader(f):
            seen[row["bucket_month"]] = int(row["n_in_bucket"])
    for m in months:
        n_month.append(seen[m])

    cat_matrix = pivot_monthly_shares(cat_csv, cat_order, months)
    lang_matrix = pivot_monthly_shares(lang_csv, lang_order, months)

    dynamics_body = resolve_dynamics_body_html(
        run_id,
        months=months,
        month_labels=labels,
        cats=cats,
        total=total,
        cat_matrix=cat_matrix,
        langs=langs,
        lang_total=lang_total,
        lang_matrix=lang_matrix,
        lang_order=lang_order,
        n_month=n_month,
        time_agg_month_csv=run_dir / "time_agg_month.csv",
    )

    pie_labels = [category_label(c) for c in cat_order]
    pie_pct = [round(100 * cats[c] / total, 2) for c in cat_order]
    pie_colors = hsl_colors(len(cat_order))

    cat_datasets_js = []
    cols = hsl_colors(len(cat_order))
    for i, c in enumerate(cat_order):
        cat_datasets_js.append(
            {
                "label": category_label(c),
                "data": cat_matrix[c],
                "backgroundColor": cols[i],
                "borderWidth": 0,
            }
        )

    lang_datasets_js = []
    lcols = hsl_colors(len(lang_order))
    for i, c in enumerate(lang_order):
        lang_datasets_js.append(
            {
                "label": lang_label(c),
                "data": lang_matrix[c],
                "backgroundColor": lcols[i],
                "borderWidth": 0,
            }
        )

    mdict = json.loads((run_dir / "metrics_dictionary.json").read_text(encoding="utf-8"))
    desc_ru = {m["name"]: m.get("description_ru", m.get("description", "")) for m in mdict["metrics"]}

    figures_root = run_dir / "figures"
    gallery_rows: list[str] = []
    gallery_rows.append(
        f'<figure class="border rounded-xl p-4 bg-white"><img src="{_png_data_uri(figures_root / "language_share_day.png")}" '
        f'alt="" loading="lazy" class="w-full"/><figcaption class="caption mt-2">'
        f"<strong>Языки по суткам</strong> — каждый столбец это один день; цветные слои показывают, "
        f"какую долю записей того дня детектор отнёс к какому языку (по трём выдержкам текста: начало, середина, конец). "
        f"Сопоставляйте с объёмом записей в тот же день: в дни с малым числом транскриптов доли «прыгают» сильнее.</figcaption></figure>"
    )
    for name in DAY_METRICS:
        title, expl = METRIC_FRIENDLY.get(name, (name.replace("_", " "), desc_ru.get(name, "")))
        gallery_rows.append(
            f'<figure class="border rounded-xl p-4 bg-white"><img src="{_png_data_uri(figures_root / "day" / f"{name}.png")}" '
            f'alt="" loading="lazy" class="w-full"/><figcaption class="caption mt-2">'
            f"<strong>{escape(title)}</strong> — {escape(expl)}</figcaption></figure>"
        )
    gallery_html = "\n".join(gallery_rows)

    labels_js = json.dumps(labels, ensure_ascii=False)
    n_js = json.dumps(n_month)
    pie_labels_js = json.dumps(pie_labels, ensure_ascii=False)
    pie_pct_js = json.dumps(pie_pct)
    pie_colors_js = json.dumps(pie_colors)
    cat_ds_js = json.dumps(cat_datasets_js, ensure_ascii=False)
    lang_ds_js = json.dumps(lang_datasets_js, ensure_ascii=False)

    top3 = sorted(cats.items(), key=lambda x: -x[1])[:3]
    top3_txt = ", ".join(f"{category_label(k)} ({round(100 * v / total, 1)}%)" for k, v in top3)

    methodology_html = build_content_category_methodology_html()

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Итоговый исследовательский отчёт — transcriptions-analysis</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    .chart-container {{ position: relative; height: 320px; }}
    .chart-container-stacked {{ position: relative; height: 440px; }}
    .chart-container-pie {{ position: relative; height: 380px; max-width: 520px; margin: 0 auto; }}
    .caption {{ font-size: 0.875rem; color: #4b5563; line-height: 1.5; }}
    figure img {{ max-width: 100%; height: auto; }}
    code {{ font-size: 0.85em; }}
  </style>
</head>
<body class="bg-zinc-50 text-zinc-900">
  <div class="max-w-6xl mx-auto p-6 md:p-10 bg-white shadow-xl min-h-screen">
    <header class="border-b pb-8 mb-10 text-center">
      <h1 class="text-3xl md:text-4xl font-bold mb-2">Итоговый исследовательский отчёт</h1>
      <p class="text-xl text-blue-700 font-semibold">Типы контента, языки и устойчивые признаки качества транскрипций</p>
      <p class="text-sm text-zinc-500 mt-2">Идентификатор прогона: <code>{escape(str(run_id_display))}</code></p>
      <p class="text-zinc-600 mt-4 text-sm">Выборка: <strong>{manifest["rows_read"]:,}</strong> транскриптов
        за период <strong>{manifest["created_at_min"]}</strong> — <strong>{manifest["created_at_max"]}</strong></p>
      <p class="text-xs text-zinc-400 mt-2">Версия набора метрик: {manifest["metrics_definition_version"]} ·
        Дата прогона (UTC): {manifest.get("created_utc", "—")}</p>
    </header>

    <section class="mb-10 grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="border rounded-2xl p-4 text-center">
        <div class="text-3xl font-bold text-blue-600">{total:,}</div>
        <div class="text-sm text-zinc-500 mt-1">Записей в анализе</div>
      </div>
      <div class="border rounded-2xl p-4 text-center">
        <div class="text-3xl font-bold text-emerald-600">{round(100 * cats.get("business_work", 0) / total, 1)}%</div>
        <div class="text-sm text-zinc-500 mt-1">Бизнес и работа</div>
      </div>
      <div class="border rounded-2xl p-4 text-center">
        <div class="text-3xl font-bold text-amber-600">{round(100 * cats.get("general_monologue", 0) / total, 1)}%</div>
        <div class="text-sm text-zinc-500 mt-1">Монологи / размышления</div>
      </div>
      <div class="border rounded-2xl p-4 text-center">
        <div class="text-3xl font-bold text-violet-600">{round(100 * cats.get("dialogue_meeting", 0) / total, 1)}%</div>
        <div class="text-sm text-zinc-500 mt-1">Диалоги и совещания</div>
      </div>
    </section>

    <section class="mb-10 text-sm leading-relaxed text-zinc-800 space-y-4">
      <h2 class="text-2xl font-semibold text-zinc-900 mb-3 border-b pb-2">Что сделано и откуда взялись цифры</h2>
      <p>В основе лежит полный экспорт транскрипций из мессенджера: у каждой записи указаны дата создания, текст с
        разметкой спикеров и времени, а также имя исходного файла. <strong>Пайплайн последовательно</strong> обрабатывает
        такие строки — разбирает структуру диалога (слой A), вычисляет текстовые и языковые статистики (слой B),
        присваивает каждой записи <strong>основной тип контента</strong> по правилам ключевых слов и структуры реплик,
        затем <strong>сводит показатели по времени</strong> по календарным дням, ISO-неделям и календарным месяцам.
        Для каждого интервала сохраняются медиана, нижний и верхний квартили и число записей; по ним оцениваются
        типичный уровень метрики, разброс и представительность интервала.</p>
      <p>Доли категорий контента и языков считаются отдельно: внутри каждого месяца показано, какая часть записей
        попала в ту или иную категорию или язык (в сумме по категориям / языкам внутри месяца получается 100%).
        Глобальные доли на круговой диаграмме — это сколько записей каждого типа было во всей выборке целиком.</p>
      <p class="text-zinc-600">Итог воспроизводим: зафиксированы версия метрик, объём и диапазон дат, контрольная
        информация о входном файле (см. служебный manifest прогона при необходимости аудита).</p>
    </section>

    <section class="mb-10 text-sm leading-relaxed border-l-4 border-blue-200 pl-5 py-1">
      <h2 class="text-lg font-semibold text-zinc-900 mb-2">Как читать графики со временной шкалой по дням</h2>
      <p class="text-zinc-700">Ниже по странице приведены сохранённые графики показателей по <strong>суткам даты
        создания</strong> записи. На каждом таком графике: <strong>линия по центру</strong> — медиана (типичное
        значение) по всем транскриптам этого дня; <strong>полупрозрачная полоса</strong> — разброс между типичным
        «низом» и «верхом» (межквартильный интервал); <strong>столбцы на фоне</strong> (вторая шкала) — сколько
        записей попало в этот день. Резкие изломы на отдельных днях чаще всего связаны с <strong>малым числом
        записей</strong> в этот день, а не с «поломкой» модели распознавания.</p>
    </section>

    <section class="mb-10">
      <h2 class="text-2xl font-semibold mb-4 border-b pb-2">Состав выборки: все типы контента</h2>
      <p class="text-sm text-zinc-600 mb-4">Каждая запись отнесена ровно к одной категории. На круговой диаграмме —
        полное распределение по всем классам; в таблице справа те же числа в процентах и в количестве записей.</p>
      <div class="grid md:grid-cols-2 gap-8 items-start">
        <div class="chart-container-pie"><canvas id="overallPie"></canvas></div>
        <div class="text-sm">
          <p class="font-medium text-zinc-800 mb-2">Крупнейшие группы: {escape(top3_txt)}</p>
          <div class="max-h-80 overflow-y-auto border rounded-lg">
            <table class="w-full text-xs border-collapse">
              <thead><tr class="bg-zinc-100"><th class="border p-2 text-left">Тип</th><th class="border p-2 text-right">%</th><th class="border p-2 text-right">Записей</th></tr></thead>
              <tbody>
                {"".join(
                    f'<tr><td class="border p-2">{escape(category_label(k))}</td>'
                    f'<td class="border p-2 text-right">{round(100 * v / total, 2)}</td>'
                    f'<td class="border p-2 text-right">{v}</td></tr>'
                    for k, v in sorted(cats.items(), key=lambda x: -x[1])
                )}
              </tbody>
            </table>
          </div>
          <p class="text-xs text-zinc-500 mt-3">Классификация эвристическая: она отражает лексику и структуру текста,
            а не «истинную» тему разговора. Для продуктовых выводов сочетайте её с ручной выборкой.</p>
        </div>
      </div>
    </section>

    <section class="mb-10">
      <h2 class="text-2xl font-semibold mb-4 border-b pb-2">Как меняется смесь типов контента по месяцам</h2>
      <p class="text-sm text-zinc-600 mb-3">Каждый столбец — один календарный месяц; цветные слои набирают в сумме
        100% и показывают, какая доля записей месяца отнесена к каждому типу. Так удобно видеть сдвиги аудитории
        и сценариев использования, не смешивая их с техническим качеством распознавания.</p>
      <div class="chart-container-stacked"><canvas id="monthlyCatStack"></canvas></div>
      <p class="caption mt-3">Если в каком-то месяце заметно меньше записей (см. следующий график), интерпретируйте
        тонкие изменения долей осторожно: статистика по «узкому» месяцу менее устойчива.</p>
    </section>

    <section class="mb-10">
      <h2 class="text-2xl font-semibold mb-4 border-b pb-2">Объём данных по месяцам</h2>
      <p class="text-sm text-zinc-600 mb-3">Сколько транскриптов попало в каждый месяц по дате создания. Это базовая
        мера «насколько можно доверять» месячным долям и дневным графикам внутри месяца.</p>
      <div class="chart-container"><canvas id="monthlyN"></canvas></div>
    </section>

    <section class="mb-10">
      <h2 class="text-2xl font-semibold mb-4 border-b pb-2">Языки: полная картина по месяцам</h2>
      <p class="text-sm text-zinc-600 mb-3">Для каждой записи определяется основной язык; здесь показаны
        <strong>все</strong> встречающиеся метки, включая случаи, когда язык не удалось уверенно назначить.
        Рост доли английского и других языков обычно отражает смену тематики и каналов, а не только ошибку детектора.</p>
      <div class="chart-container-stacked"><canvas id="monthlyLangStack"></canvas></div>
    </section>

    <section class="mb-10 bg-slate-50 border border-slate-200 rounded-2xl p-6 text-sm leading-relaxed">
      <h2 class="text-xl font-semibold text-slate-900 mb-4">Выводы по динамике</h2>
      {dynamics_body}
    </section>

    <section class="mb-10">
      <h2 class="text-2xl font-semibold mb-4 border-b pb-2">Графики показателей и языковой смеси по дням</h2>
      <p class="text-sm text-zinc-600 mb-6">Подписи к каждому рисунку сформулированы так, чтобы по смыслу можно было
        понять показатель без чтения внутренних имён полей. Технические определения по-прежнему лежат в словаре метрик
        прогона при необходимости юридического или инженерного аудита.</p>
      <div class="grid md:grid-cols-2 gap-6">
        {gallery_html}
      </div>
    </section>

    {methodology_html}

    <footer class="text-center text-xs text-zinc-400 pt-8 border-t leading-relaxed">
      Отчёт собран автоматически из результатов аналитического прогона; графики по суткам встроены в файл (PNG в base64), перенос возможен без каталога <code>figures/</code>.<br/>
      Другой прогон: <code>python scripts/build_final_research_report.py --run-id &lt;uuid&gt;</code>
      (или переменная окружения <code>FINAL_REPORT_RUN_ID</code>). Опционально: <code>-o путь/к/отчёту.html</code>.
    </footer>
  </div>

  <script>
    const LABELS = {labels_js};
    const N_MONTH = {n_js};
    const PIE_L = {pie_labels_js};
    const PIE_P = {pie_pct_js};
    const PIE_COL = {pie_colors_js};
    const CAT_DATASETS = {cat_ds_js};
    const LANG_DATASETS = {lang_ds_js};

    new Chart(document.getElementById('overallPie'), {{
      type: 'pie',
      data: {{
        labels: PIE_L,
        datasets: [{{ data: PIE_P, backgroundColor: PIE_COL }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'right', labels: {{ boxWidth: 12, font: {{ size: 10 }} }} }},
          tooltip: {{ callbacks: {{ label: ctx => ctx.label + ': ' + ctx.raw + '%' }} }}
        }}
      }}
    }});

    new Chart(document.getElementById('monthlyN'), {{
      type: 'bar',
      data: {{
        labels: LABELS,
        datasets: [{{ label: 'Число записей', data: N_MONTH, backgroundColor: '#64748b' }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{
          y: {{ beginAtZero: true, title: {{ display: true, text: 'Записей в месяце' }} }}
        }},
        plugins: {{ legend: {{ display: false }} }}
      }}
    }});

    new Chart(document.getElementById('monthlyCatStack'), {{
      type: 'bar',
      data: {{ labels: LABELS, datasets: CAT_DATASETS }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{
          x: {{ stacked: true }},
          y: {{
            stacked: true,
            max: 100,
            title: {{ display: true, text: 'Доля внутри месяца, %' }}
          }}
        }},
        plugins: {{
          legend: {{ position: 'bottom', labels: {{ boxWidth: 10, font: {{ size: 9 }} }} }},
          tooltip: {{ mode: 'index', intersect: false }}
        }}
      }}
    }});

    new Chart(document.getElementById('monthlyLangStack'), {{
      type: 'bar',
      data: {{ labels: LABELS, datasets: LANG_DATASETS }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{
          x: {{ stacked: true }},
          y: {{
            stacked: true,
            max: 100,
            title: {{ display: true, text: 'Доля внутри месяца, %' }}
          }}
        }},
        plugins: {{
          legend: {{ position: 'bottom', labels: {{ boxWidth: 10, font: {{ size: 9 }} }} }},
          tooltip: {{ mode: 'index', intersect: false }}
        }}
      }}
    }});
  </script>
</body>
</html>
"""

    final_path = output_html if output_html is not None else DEFAULT_FINAL_HTML
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(html, encoding="utf-8")
    print(f"Wrote {final_path}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Собрать итоговый HTML-отчёт из каталога outputs/<run-id>/ (manifest, share CSV, figures)."
    )
    p.add_argument(
        "--run-id",
        default=os.environ.get("FINAL_REPORT_RUN_ID"),
        help="Имя подпапки в outputs/ (UUID прогона). Если не задано — используется переменная окружения FINAL_REPORT_RUN_ID.",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=f"Куда записать HTML (по умолчанию: {DEFAULT_FINAL_HTML})",
    )
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    if not args.run_id or not str(args.run_id).strip():
        print(
            "error: укажите идентификатор прогона: --run-id <uuid>\n"
            "  или задайте переменную окружения FINAL_REPORT_RUN_ID (имя папки в outputs/).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    main(str(args.run_id).strip(), output_html=args.output)
