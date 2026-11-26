"""Tests for the pure modules (no third-party packages needed):  python -m unittest discover -s tests"""
import json
import os
import unittest
from types import SimpleNamespace as NS

from app import context, kaggle_parse, textutil


def ev(kind, **data):
    return NS(kind=kind, data=data)


def model_ev(text, calls):
    return ev("model", content_json=json.dumps({"role": "model", "text": text}), text=text, calls=calls)


def result_ev(*names):
    return ev("tool_result", results=[{"name": n, "response": {"ok": True, "data": {}}} for n in names], ui=[])


class Redaction(unittest.TestCase):
    def test_env_and_patterns(self):
        os.environ["HF_TOKEN"] = "hf_" + "a" * 30
        os.environ["GEMINI_API_KEY"] = "AIza" + "b" * 35
        txt = f"token {os.environ['HF_TOKEN']} and key {os.environ['GEMINI_API_KEY']} and KGAT_abcdefghijk1234"
        out = textutil.redact(txt)
        self.assertNotIn("hf_aaaa", out)
        self.assertNotIn("AIzabbbb", out)
        self.assertNotIn("KGAT_abc", out)
        self.assertEqual(out.count("[REDACTED]"), 3)

    def test_kaggle_json_token(self):
        os.environ["KAGGLE_API_TOKEN"] = json.dumps({"username": "u", "key": "supersecretkey123"})
        self.assertNotIn("supersecretkey123", textutil.redact("log: supersecretkey123"))

    def test_shrink_and_short_args(self):
        self.assertLess(len(textutil.shrink("x" * 10000, 1000)), 1100)
        self.assertEqual(textutil.short_args({"code": "y" * 500, "slug": "abc"})["code"], "<500 chars>")


class KaggleParsing(unittest.TestCase):
    def test_status(self):
        cases = {
            'user/error-analysis has status "KernelWorkerStatus.COMPLETE"': "complete",
            'user/my-kernel has status "running"': "running",
            'user/my-kernel has status "error"': "error",
            'user/my-kernel has status "queued"': "queued",
            'user/my-kernel has status "cancelAcknowledged"': "cancelled",
            "garbage": "unknown",
        }
        for text, want in cases.items():
            self.assertEqual(kaggle_parse.parse_status(text), want, text)

    def test_slug_rules(self):
        self.assertTrue(kaggle_parse.SLUG.match("my-model-run"))
        self.assertFalse(kaggle_parse.SLUG.match("My Model"))
        self.assertFalse(kaggle_parse.SLUG.match("abc"))
        self.assertEqual(kaggle_parse.title_from_slug("my-model-run"), "My Model Run")

    def test_log_extraction(self):
        raw = json.dumps([{"stream_name": "stdout", "time": 1, "data": "hello\n"}, {"stream_name": "stderr", "time": 2, "data": "oops\n"}])
        self.assertEqual(kaggle_parse.extract_log_text(raw), "hello\noops\n")
        self.assertEqual(kaggle_parse.extract_log_text("plain text"), "plain text")


class History(unittest.TestCase):
    def test_pairing_and_deferred_user_text(self):
        events = [
            ev("user", text="goal"),
            model_ev("", [{"name": "a", "args": {}}]),
            ev("user", text="extra instruction while tool runs"),
            result_ev("a"),
            model_ev("done?", []),
        ]
        h = context.build_history(events)
        self.assertEqual([x["role"] for x in h], ["user", "model", "user", "model"])
        self.assertIn("responses", h[2])
        self.assertEqual(h[2]["text_parts"], ["extra instruction while tool runs"])

    def test_system_events_merge_into_user_turn(self):
        events = [ev("user", text="goal"), model_ev("", [{"name": "w", "args": {}}]), result_ev("w"), ev("system", text="kernel finished")]
        h = context.build_history(events)
        self.assertEqual(h[-1]["text_parts"], ["[system] kernel finished"])
        self.assertIn("responses", h[-1])

    def test_trim_keeps_goal_pairs_and_user_text(self):
        events = [ev("user", text="goal")]
        for i in range(30):
            events.append(model_ev("", [{"name": "a", "args": {}}]))
            events.append(result_ev("a"))
            events[-1].data["results"][0]["response"]["data"] = {"blob": "z" * 2000}
        events.append(ev("user", text="NEW INSTRUCTION"))
        events.append(model_ev("", [{"name": "a", "args": {}}]))
        events.append(result_ev("a"))
        h = context.build_history(events)
        t = context.trim_history(h, max_chars=20000)
        self.assertLess(sum(len(json.dumps(x)) for x in t), 30000)
        self.assertEqual(t[0]["role"], "user")
        self.assertIn("goal", t[0]["text_parts"][0])
        # strict alternation and every responses-turn directly follows a model turn
        for a, b in zip(t, t[1:]):
            self.assertNotEqual(a["role"], b["role"])
            if b["role"] == "user" and b.get("responses"):
                self.assertEqual(a["role"], "model")
        flat = json.dumps(t)
        self.assertIn("NEW INSTRUCTION", flat)

    def test_no_trim_when_small(self):
        h = context.build_history([ev("user", text="hi")])
        self.assertIs(context.trim_history(h, 10000), h)


class Scoring(unittest.TestCase):
    def test_keyword_score(self):
        q = textutil.tokens("kaggle error out of memory")
        hi = textutil.score(q, "Kaggle out of memory", "use smaller batch", "")
        lo = textutil.score(q, "Space deploy", "hf space", "")
        self.assertGreater(hi, lo)


if __name__ == "__main__":
    unittest.main()
