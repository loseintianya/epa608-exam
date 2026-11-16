#!/usr/bin/env python3
"""
Extract questions from the EPA 608 HTML simulators using Node.js and generate
natural Microsoft Edge Neural TTS MP3 files into ./audio/<exam>/set<N>_q<id>.mp3.
"""
import asyncio
import json
import os
import subprocess
import sys

VOICE = os.environ.get("EDGE_TTS_VOICE", "en-US-AndrewNeural")
RATE = os.environ.get("EDGE_TTS_RATE", "-5%")  # 0.95x natural exam pace

TARGETS = [
    ("type1", "epa_608_type_i_exam_simulator.html"),
    ("type2", "index.html"),
    ("type3", "epa_608_type_iii_exam_simulator.html"),
]


def extract_sets(html_path: str):
    node_script = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[1], "utf8");
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) throw new Error("No <script> block in " + process.argv[1]);
const stub = "const window = {}; const document = { getElementById: () => null };\n";
const fn = new Function(stub + m[1] + "\n; return getExamSetsData();");
const sets = fn();
process.stdout.write(JSON.stringify(sets.map((s, idx) => ({
  setNum: idx + 1,
  questions: s.questions.map(q => ({
    id: q.id,
    questionEn: q.questionEn,
    optionsEn: q.optionsEn
  }))
}))));
"""
    res = subprocess.run(
        ["node", "-e", node_script, html_path],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(res.stdout)


async def synth_one(sem: asyncio.Semaphore, text: str, out_path: str):
    import edge_tts
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        return "skipped"
    async with sem:
        for attempt in range(3):
            try:
                communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
                await communicate.save(out_path)
                return "ok"
            except Exception as exc:
                if attempt == 2:
                    raise RuntimeError(f"Failed {out_path}: {exc}") from exc
                await asyncio.sleep(1.5 * (attempt + 1))


async def main():
    sem = asyncio.Semaphore(8)
    tasks = []
    for exam_key, html_file in TARGETS:
        if not os.path.exists(html_file):
            continue
        out_dir = os.path.join("audio", exam_key)
        os.makedirs(out_dir, exist_ok=True)
        sets = extract_sets(html_file)
        for s in sets:
            set_num = s["setNum"]
            for q in s["questions"]:
                labels = ["A", "B", "C", "D"]
                opts = ". ".join(
                    f"Option {labels[i]}. {opt}" for i, opt in enumerate(q["optionsEn"])
                )
                text = f"Question {q['id']}. {q['questionEn']} {opts}"
                out_path = os.path.join(out_dir, f"set{set_num}_q{q['id']}.mp3")
                tasks.append(synth_one(sem, text, out_path))

    results = await asyncio.gather(*tasks)
    generated = sum(1 for r in results if r == "ok")
    skipped = sum(1 for r in results if r == "skipped")
    print(f"Done! Generated: {generated}, Skipped (existing): {skipped}, Total: {len(results)}")


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        for exam_key, html_file in TARGETS:
            sets = extract_sets(html_file)
            total_q = sum(len(s["questions"]) for s in sets)
            print(f"{exam_key} ({html_file}): {len(sets)} sets, {total_q} questions")
    else:
        asyncio.run(main())
