#!/usr/bin/env python3
"""Benchmark several OpenAI-compatible LLM providers on the same RAG-style prompts.

Measures time-to-first-token (TTFT), total time and tokens/sec via streaming, and
prints each answer so you can judge quality (ru + ky). Providers are configured by
environment variables; any with a missing key are skipped.

Env per provider (set the *_KEY to enable it):
  GITHUB_TOKEN            (base https://models.github.ai/inference, model openai/gpt-4o-mini)
  GROQ_API_KEY           (base https://api.groq.com/openai/v1,      model llama-3.3-70b-versatile)
  GEMINI_API_KEY         (base https://generativelanguage.googleapis.com/v1beta/openai/, model gemini-2.0-flash)
  OPENAI_API_KEY         (base https://api.openai.com/v1,           model gpt-4o-mini)
Optional overrides: <PROVIDER>_MODEL, <PROVIDER>_BASE.

Usage:  python eval/llm_bench.py
"""
import os
import time

from openai import OpenAI

PROVIDERS = [
    ("GitHub Models", "GITHUB_TOKEN", "https://models.github.ai/inference", "openai/gpt-4o-mini"),
    ("Groq",          "GROQ_API_KEY", "https://api.groq.com/openai/v1",     "llama-3.3-70b-versatile"),
    ("Gemini Flash",  "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
    ("OpenAI",        "OPENAI_API_KEY", "https://api.openai.com/v1",         "gpt-4o-mini"),
]

SYSTEM = ("Ты — AI-консультант университета Ала-Тоо. Отвечай ТОЛЬКО по контексту, "
          "кратко, на языке вопроса. Если ответа нет — скажи об этом.")

CASES = [
    ("ru", "В каком кабинете сидит ректор и кто отдел кадров?",
     "Ректорат\n- Эсеналиева Назира Солтонбековна — Ректор — кабинет А315\n"
     "Отдел кадров: hr@alatoo.edu.kg. Приёмная комиссия — блок А, кабинет 107."),
    ("ky", "ОРТ үчүн канча балл керек жана медицинага кайсы предметтер?",
     "Бардык бакалавриат программалары үчүн ОРТ босого баллы — 110. "
     "Медицина (Дарылоо иши): химия жана биология (60+ балл)."),
]


def bench(name, base, model, key):
    client = OpenAI(api_key=key, base_url=base, timeout=60)
    rows = []
    for lang, q, ctx in CASES:
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "system", "content": "КОНТЕКСТ:\n" + ctx},
                {"role": "user", "content": q}]
        t0 = time.time(); ttft = None; n = 0; ans = []
        try:
            stream = client.chat.completions.create(model=model, messages=msgs,
                                                    temperature=0.2, stream=True)
            for ch in stream:
                d = ch.choices[0].delta.content if ch.choices else None
                if d:
                    if ttft is None:
                        ttft = time.time() - t0
                    n += 1; ans.append(d)
            total = time.time() - t0
            tps = n / total if total else 0
            rows.append((lang, ttft, total, tps, "".join(ans)))
        except Exception as e:
            rows.append((lang, None, None, 0, "ERROR: " + str(e)[:160]))
    return rows


def main():
    print("=== LLM provider benchmark (RAG-style, streaming) ===\n")
    summary = []
    for name, key_env, base, model in PROVIDERS:
        base = os.environ.get(name.upper().split()[0] + "_BASE", base)
        model = os.environ.get(name.upper().split()[0] + "_MODEL", model)
        key = os.environ.get(key_env, "")
        if not key:
            print(f"-- {name}: SKIP (no {key_env})\n")
            continue
        print(f"== {name}  (model={model}) ==")
        rows = bench(name, base, model, key)
        ttfts = [r[1] for r in rows if r[1] is not None]
        avg_ttft = sum(ttfts) / len(ttfts) if ttfts else None
        for lang, ttft, total, tps, ans in rows:
            if ttft is None:
                print(f"  [{lang}] {ans}")
            else:
                print(f"  [{lang}] TTFT {ttft:.2f}s | total {total:.2f}s | {tps:.0f} tok/s")
                print(f"        {ans[:200].replace(chr(10),' ')}")
        if avg_ttft is not None:
            summary.append((name, avg_ttft))
        print()
    if summary:
        print("=== Ranking by avg TTFT (faster first) ===")
        for name, t in sorted(summary, key=lambda x: x[1]):
            print(f"  {t:.2f}s  {name}")


if __name__ == "__main__":
    main()
