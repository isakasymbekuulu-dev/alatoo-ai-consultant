#!/usr/bin/env python3
"""Regression eval for the Ala-Too RAG consultant.

Sends a fixed question bank to the OpenAI-compatible API and checks each answer
contains the expected facts (case-insensitive, Cyrillic/Latin-lookalike tolerant).
Prints a table and exits non-zero if the pass rate is below the threshold — so it
can gate CI or be run by hand after data/retrieval changes.

Usage:
    ALATOO_BASE_URL=https://chat.alatoogpt.xyz python eval/qa_eval.py
    python eval/qa_eval.py --base http://localhost:8000 --threshold 0.9
"""
import argparse
import json
import os
import sys
import urllib.request

# Each item: question + list of expected substrings (ALL must appear).
BANK = [
    ("Кто ректор университета?", ["эсеналиева"]),
    ("В каком кабинете находится приёмная комиссия?", ["107"]),
    ("Кто сидит в кабинете A206?", ["администратор"]),
    ("Какой минимальный балл ОРТ нужен для поступления на бакалавриат?", ["110"]),
    ("Какие дополнительные предметы ОРТ нужны для поступления на медицину?", ["хими", "биолог"]),
    ("Есть ли у университета общежитие?", ["нет"]),
    ("Какие документы нужны для поступления на бакалавриат?", ["аттестат", "орт", "паспорт"]),
    ("Кем можно работать после программы кибербезопасности?", ["пентест"]),
    ("На каких языках ведётся обучение?", ["английск"]),
    ("С какими вузами есть программы двойного диплома?", ["solbridge", "inha"]),
    ("Какой пароль от Wi-Fi для студентов?", ["123456789"]),
    ("Есть ли гранты или бюджетные места?", ["контракт", "скидк"]),
    ("Как связаться с карьерным центром и где он находится?", ["101", "careerhub"]),
    ("Какие программы подойдут, если я люблю бизнес и лидерство?", ["менеджмент"]),
    ("На каких программах доступна дистанционная форма обучения?", ["менеджмент"]),
    ("Можно ли поступить после колледжа сразу на 2-й курс?", ["b2"]),
    ("Как связаться с магистратурой?", ["postgraduate"]),
    ("Где находится столовая и какой средний чек?", ["180"]),
    ("Какие документы нужны для поступления на PhD?", ["диплом", "автобиограф"]),
    ("Как связаться с деканатом инженерии и информатики?", ["fei@alatoo", "202"]),
    # Negative / off-topic: must NOT hallucinate, should defer.
    ("Есть ли в университете военная кафедра?", ["приёмн"]),
    ("Какая сегодня погода в Бишкеке?", ["погод"]),
]

_MAP = str.maketrans("аеосрхну", "aeocpxhy")  # Cyrillic -> Latin lookalikes


def norm(s: str) -> str:
    return s.lower().translate(_MAP)


def ask(base: str, question: str, timeout: int = 60) -> str:
    body = json.dumps({
        "model": "alatoo-rag", "stream": False,
        "messages": [{"role": "user", "content": question}],
    }).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("ALATOO_BASE_URL", "https://chat.alatoogpt.xyz"))
    ap.add_argument("--threshold", type=float, default=0.9)
    args = ap.parse_args()

    print("Eval against %s (%d questions)\n" % (args.base, len(BANK)))
    passed = 0
    for q, expect in BANK:
        try:
            ans = ask(args.base, q)
            na = norm(ans)
            missing = [k for k in expect if norm(k) not in na]
            ok = not missing
        except Exception as e:
            ok, missing, ans = False, ["<error: %s>" % e], ""
        passed += ok
        mark = "PASS" if ok else "FAIL"
        print("[%s] %s" % (mark, q))
        if not ok:
            print("       missing: %s | got: %s" % (missing, ans[:120].replace("\n", " ")))

    rate = passed / len(BANK)
    print("\n%d/%d passed (%.0f%%)" % (passed, len(BANK), rate * 100))
    return 0 if rate >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
