#!/usr/bin/env python3
"""Interactive PrescreenPipeline walkthrough — you answer every question.

This is the interactive sibling of ``simulate_pipeline.py``.  Where that script
auto-generates mock answers to drive the pipeline unattended, this one *stops at
every question* and lets you type the answer in the terminal — a REPL-style
walkthrough of the full 8-phase rule-based flow (demographics, ER critical,
symptom selection, ER checklist, OLDCARTS, past history, personal history, OPD)
plus the LLM questioning and prediction stages.

The interaction style is modelled on a Claude Code session: each question is
printed with its choices, you answer at a ``›`` prompt, the answer is echoed
back, and invalid input is re-prompted instead of crashing the run.  At any
prompt, ``:q`` aborts the session, ``:s`` skips an optional field, and
``:b`` (or **Tab** in a select menu) opens the question navigator — a list
of every answered question that you can arrow-key through to jump back and
revise an earlier answer.  Single- and multi-select prompts use arrow-key
navigation on a TTY (↑↓ to move, Enter to confirm, Space to toggle in
multi-select); pass ``--no-tui`` to force the line-buffered fallback.

Like ``simulate_pipeline.py`` this uses the test-suite mock DB
(``MockRepository``, imported from ``tests/`` at runtime) so it needs no real
database.  The LLM components default to in-process mocks and can be swapped for
the real SDK connectors via ``--question_generation_backend`` /
``--prediction_backend`` — those read their credentials from ``.env``, loaded at
startup.

Usage::

    # Walk through the default symptom (Headache), choosing it interactively
    python scripts/interactive_pipeline.py

    # Preset the primary symptom up front (skips the phase-2 prompt)
    python scripts/interactive_pipeline.py -s Fever

    # Skip the tedious ER yes/no phases (auto-answer "no")
    python scripts/interactive_pipeline.py --skip-er

    # Run all 8 phases through to LLM prediction (no early exit)
    python scripts/interactive_pipeline.py --disable-early-termination

    # Drive the real medgemma predictor (config sourced from .env)
    python scripts/interactive_pipeline.py --disable-early-termination \
        --prediction_backend medgemma_prescreen --question_generation_backend none

    # List the available NHSO symptoms
    python scripts/interactive_pipeline.py --list-symptoms
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import select
import shutil
import sys
import termios
import tty
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so we can import both the SDK and the
# test mock infrastructure (mirrors simulate_pipeline.py).
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT / "tests"))
sys.path.insert(0, str(_REPO_ROOT / "src"))

# Load .env *before* importing the SDK so the real LLM backends (selected via
# --question_generation_backend / --prediction_backend) can resolve their
# credentials and endpoints, and env-driven constants are picked up too.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_REPO_ROOT / ".env")

from unittest.mock import AsyncMock  # noqa: E402

from test_engine import MockRepository  # noqa: E402

from prescreen_rulesets.constants import AUTO_EVAL_TYPES  # noqa: E402
from prescreen_rulesets.engine import (  # noqa: E402
    PrescreenEngine,
    _evaluate_field_condition,
)
from prescreen_rulesets.evaluator import ConditionalEvaluator  # noqa: E402
from prescreen_rulesets.interfaces import PredictionModule, QuestionGenerator  # noqa: E402
from prescreen_rulesets.models.action import GotoAction, TerminateAction  # noqa: E402
from prescreen_rulesets.models.pipeline import (  # noqa: E402
    DiagnosisResult,
    GeneratedQuestions,
    LLMAnswer,
    LLMQuestionsStep,
    PipelineResult,
    PredictionResult,
    QAPair,
)
from prescreen_rulesets.models.session import QuestionsStep, TerminationStep  # noqa: E402
from prescreen_rulesets.pipeline import PrescreenPipeline  # noqa: E402
from prescreen_rulesets.ruleset import RulesetStore  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_ID = "interactive_user"
SESSION_ID = "interactive_session"
_DEFAULT_SYMPTOM = "Headache"

# The 8-phase rule-based flow splits into bulk phases (a whole form submitted at
# once) and sequential phases (one question per step, phases 4 & 7).  This set
# only drives the "bulk"/"sequential" label in the phase header.
_BULK_PHASES = frozenset({0, 1, 2, 3, 5, 6})
# ER phases — bulk yes/no checklists keyed by qid.  --skip-er auto-answers these.
_ER_PHASES = frozenset({1, 3})

# Fixed Thai follow-up questions returned by the `sim` question generator.
MOCK_LLM_QUESTIONS = [
    "อาการปวดรุนแรงแค่ไหน?",
    "มีอาการคลื่นไส้ร่วมด้วยไหม?",
]


# ---------------------------------------------------------------------------
# Mock LLM components (the `sim` backend — default for both backend flags)
# ---------------------------------------------------------------------------
# These mirror simulate_pipeline.py so a plain interactive run stays fully
# offline.  The --question_generation_backend / --prediction_backend flags can
# swap in the real SDK connectors instead.


class SimQuestionGenerator(QuestionGenerator):
    """Returns a fixed set of Thai follow-up questions."""

    async def generate(self, qa_pairs: list[QAPair]) -> GeneratedQuestions:
        return GeneratedQuestions(questions=MOCK_LLM_QUESTIONS)


class SimPredictionModule(PredictionModule):
    """Returns two mock diagnoses (ranked most-likely first).

    ``d437`` (Upper respiratory tract infections) is telemedicine-eligible per
    v1/const/disease_reasons.yaml, so it exercises the disease-driven custom
    termination reason; ``d001`` is unconfigured and verifies the "any match
    wins" scan skips it.  ``DiagnosisResult`` carries only ``disease_id`` — no
    confidence score is exposed, by design.
    """

    async def predict(self, qa_pairs: list[QAPair]) -> PredictionResult:
        return PredictionResult(
            diagnoses=[
                DiagnosisResult(disease_id="d001"),
                DiagnosisResult(disease_id="d437"),
            ],
            departments=[],
            severity=None,
        )


def _build_generator(backend: str) -> QuestionGenerator | None:
    """Construct the question generator selected by --question_generation_backend.

    - ``sim``    — the in-process mock (default; offline)
    - ``none``   — disabled; the pipeline skips the LLM questioning stage
    - ``openai`` — the real ``OpenAIQuestionGenerator`` (needs ``OPENAI_API_KEY``
                   or ``OPENROUTER_API_KEY`` in the environment / .env)
    """
    if backend == "sim":
        return SimQuestionGenerator()
    if backend == "none":
        return None
    if backend == "openai":
        from prescreen_rulesets.question_generator import OpenAIQuestionGenerator
        return OpenAIQuestionGenerator()
    raise ValueError(f"Unknown question generation backend: {backend!r}")


def _build_predictor(store: RulesetStore, backend: str) -> PredictionModule:
    """Construct the prediction module selected by --prediction_backend.

    - ``sim``                — the in-process mock (default; offline)
    - ``openai``             — the real ``OpenAIPredictionModule``
    - ``medgemma_prescreen`` — the real ``MedgemmaPredictionModule`` (needs
                               ``VLLM_PREDICTOR_URL`` / ``VLLM_PREDICTOR_MODEL``
                               in the environment / .env)
    """
    if backend == "sim":
        return SimPredictionModule()
    if backend == "openai":
        from prescreen_rulesets.prediction import OpenAIPredictionModule
        return OpenAIPredictionModule(store=store)
    if backend == "medgemma_prescreen":
        from prescreen_rulesets.prediction import MedgemmaPredictionModule
        return MedgemmaPredictionModule(store=store)
    raise ValueError(f"Unknown prediction backend: {backend!r}")


# ---------------------------------------------------------------------------
# Terminal styling
# ---------------------------------------------------------------------------
# Plain ANSI escapes — the SDK ships no `rich` dependency, so we keep zero extra
# dependencies.  Colour is toggled off by --no-color or a non-TTY stdout
# (`_USE_COLOR` is finalised in main() before any output is produced).  TUI
# mode (arrow-key select menus + the question navigator) is a separate gate
# (`_USE_TUI`) because a user may want SGR colour without raw-mode capture
# (e.g. piping through ``tee``) or vice-versa.

_USE_COLOR = True
_USE_TUI = True
# Inline ``:b back`` reminder shown next to every line prompt's ``›``.  The
# main loop flips this False during the LLM-questioning block (where the
# engine forbids back-edit) and inside the line-mode navigator's own picker
# (where ``:b`` would recurse), so the hint only appears where the command
# actually works.
_NAV_AVAILABLE = True


def _style(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def bold(t: str) -> str:
    return _style(t, "1")


def dim(t: str) -> str:
    return _style(t, "2")


def red(t: str) -> str:
    return _style(t, "31")


def green(t: str) -> str:
    return _style(t, "32")


def yellow(t: str) -> str:
    return _style(t, "33")


def cyan(t: str) -> str:
    return _style(t, "36")


def magenta(t: str) -> str:
    return _style(t, "35")


# ---------------------------------------------------------------------------
# Raw-mode key input  (POSIX termios; powers the arrow-key TUI prompts and
# the question navigator below)
# ---------------------------------------------------------------------------
# Single-byte and CSI escape sequences are translated to canonical key names
# so callers never have to think in bytes.  Everything here is plain stdlib —
# no `prompt_toolkit` / `readchar` / `curses` — matching the script's
# zero-TUI-deps stance.

# Canonical key names returned by ``read_key()``.  Printable characters are
# returned as themselves (length-1 ``str``); only the non-printable keys we
# actively care about get a constant.
KEY_UP        = "UP"
KEY_DOWN      = "DOWN"
KEY_LEFT      = "LEFT"
KEY_RIGHT     = "RIGHT"
KEY_ENTER     = "ENTER"
KEY_SPACE     = "SPACE"
KEY_TAB       = "TAB"
KEY_ESC       = "ESC"
KEY_BACKSPACE = "BACKSPACE"
KEY_HOME      = "HOME"
KEY_END       = "END"
KEY_PGUP      = "PGUP"
KEY_PGDN      = "PGDN"


# Test harness: when ``THAILLM_INTERACTIVE_DEBUG=1`` is set, ``main()`` may
# pre-populate this queue from ``--debug-keys``; ``read_key`` then drains it
# instead of touching the real terminal.  Empty in normal runs.
_DEBUG_KEY_QUEUE: list[str] = []


@contextlib.contextmanager
def _raw_mode(stream=sys.stdin):
    """Switch the terminal into cbreak mode for the duration of a TUI prompt.

    Snapshots and restores the termios state — on clean exit, on raised
    exceptions, and on KeyboardInterrupt — so the user's shell always recovers
    a working line-buffered terminal.  Also hides the cursor while the prompt
    is active and brings it back on exit.

    When ``stream`` isn't a TTY we skip the termios calls entirely.  This
    matters for the ``--force-tui`` debug harness, where ``_USE_TUI`` is True
    but stdin is piped — ``termios.tcgetattr`` would raise
    ``error: (25, 'Inappropriate ioctl for device')`` and the run would crash
    before any TUI reader returned.  ``read_key`` then drives the prompts off
    ``_DEBUG_KEY_QUEUE`` so no real keystrokes are needed.

    We deliberately use :func:`tty.setcbreak` rather than :func:`tty.setraw`
    so Ctrl-C still surfaces as ``KeyboardInterrupt`` (a stuck TUI loop is
    always escapable) and NL→CR translation stays on for surrounding
    ``print()`` calls.
    """
    if not stream.isatty():
        # No real terminal — most likely we're in --force-tui debug mode with
        # piped stdin.  Skip termios; rendering and key reads still work.
        try:
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()
            yield
        finally:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
        return

    fd = stream.fileno()
    old_attrs = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\033[?25l")  # hide cursor
        sys.stdout.flush()
        yield
    finally:
        sys.stdout.write("\033[?25h")  # show cursor
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)


def read_key(stream=sys.stdin, *, esc_timeout: float = 0.05) -> str:
    """Read one keystroke from a raw-mode stream; return a canonical key name.

    Must be called inside a ``_raw_mode()`` block.  Returns one of the
    ``KEY_*`` constants above, or a printable character verbatim.

    Escape-sequence handling: an isolated ESC (``\\x1b``) might be the
    beginning of a CSI sequence (``ESC [ A``…) *or* a bare Esc keypress.  We
    disambiguate with a short ``select.select()`` poll — if no follow-up byte
    arrives within ``esc_timeout`` seconds we return ``KEY_ESC``.  Sequences
    we don't recognise also collapse to ``KEY_ESC`` after draining their
    bytes, so they never leak into a subsequent ``input()`` call.

    Ctrl-C (``\\x03``) is re-raised as ``KeyboardInterrupt`` so the surrounding
    ``_raw_mode()`` ``finally`` clause restores the terminal.  Ctrl-D
    (``\\x04``) is translated to ``_Abort`` for consistency with the line-input
    ``:q`` command.  EOF on the input stream (empty ``os.read``) also raises
    ``_Abort`` — covers the case where a debug-keys queue is drained mid-test.

    When ``_DEBUG_KEY_QUEUE`` is non-empty (test harness mode), we pop the
    next entry instead of touching the terminal; this lets ``--debug-keys``
    drive the TUI deterministically without ``pty.spawn``.
    """
    if _DEBUG_KEY_QUEUE:
        return _DEBUG_KEY_QUEUE.pop(0)
    fd = stream.fileno()
    raw = os.read(fd, 1)
    if not raw:                  # EOF — drained stdin (e.g. debug-keys exhausted)
        raise _Abort()
    ch = raw.decode("utf-8", errors="replace")

    if ch == "\x1b":
        # Could be bare Esc or the start of a CSI / SS3 sequence.
        rlist, _, _ = select.select([fd], [], [], esc_timeout)
        if not rlist:
            return KEY_ESC
        seq = os.read(fd, 1).decode("utf-8", errors="replace")
        if seq != "[":
            return KEY_ESC
        seq2 = os.read(fd, 1).decode("utf-8", errors="replace")
        arrow_map = {
            "A": KEY_UP, "B": KEY_DOWN, "C": KEY_RIGHT, "D": KEY_LEFT,
            "H": KEY_HOME, "F": KEY_END,
        }
        if seq2 in arrow_map:
            return arrow_map[seq2]
        if seq2 in ("5", "6"):
            # PgUp/PgDn — drain the trailing '~' so it doesn't pollute the
            # next read.
            os.read(fd, 1)
            return KEY_PGUP if seq2 == "5" else KEY_PGDN
        return KEY_ESC

    if ch in ("\r", "\n"):
        return KEY_ENTER
    if ch == " ":
        return KEY_SPACE
    if ch == "\t":
        return KEY_TAB
    if ch in ("\x7f", "\b"):
        return KEY_BACKSPACE
    if ch == "\x03":         # Ctrl-C — let the surrounding _raw_mode restore the terminal
        raise KeyboardInterrupt
    if ch == "\x04":         # Ctrl-D — treat like :q at a TUI prompt
        raise _Abort()
    return ch


def _tui_available() -> bool:
    """True iff the TUI select readers and navigator can render correctly.

    All gating happens in :func:`main` — ``_USE_TUI`` is set to ``True`` only
    when stdin/stdout are real TTYs and ``--no-tui`` wasn't passed; the
    ``--force-tui`` debug flag can override that for harness runs.
    ``_USE_COLOR`` must also be on, because the cursor-escape redraws share
    the SGR-support assumption colour styling needs (``--no-color`` asks us
    to stay strictly line-buffered for piped smoke tests).
    """
    return _USE_TUI and _USE_COLOR


# Question types whose options will be re-painted by a TUI select reader —
# ``_show_question`` should suppress its static numbered list for these when
# TUI mode is active, to avoid double-rendering.
_TUI_SELECT_TYPES = frozenset({
    "enum", "from_yaml",
    "single_select", "image_single_select",
    "multi_select", "image_multi_select",
})


def _should_skip_static_options(q) -> bool:
    """True iff a TUI select reader is about to paint this question's options.

    Only considers questions that actually carry inline ``options``; the
    ``from_yaml`` case where options come from the store falls through to
    ``False`` (``_show_question`` was going to be silent there anyway).
    """
    return (
        _tui_available()
        and q.question_type in _TUI_SELECT_TYPES
        and bool(q.options)
    )


# ---------------------------------------------------------------------------
# Interactive input primitives
# ---------------------------------------------------------------------------


class _Abort(Exception):
    """Raised when the user types ``:q`` (or hits EOF/Ctrl-C) at a prompt."""


class _Skip(Exception):
    """Raised when the user types ``:s`` to skip a question.

    Always raised by :func:`_input`, but only *honoured* by callers that allow
    skipping (optional fields).  In a required context the caller catches it
    and re-prompts, so ``:s`` is harmless there.
    """


class _Navigate(Exception):
    """Raised when the user wants to jump back to a previously-answered question.

    Triggered by Tab inside a TUI select prompt or by ``:b`` / ``:back`` /
    ``:nav`` at a line-input prompt.  The payload describes where to jump:
    ``target_phase`` + optional ``target_qid`` map directly onto
    ``PrescreenPipeline.back_edit``.  When the trigger is "user wants to open
    the navigator chooser" (the usual case from a prompt), both fields are
    ``None`` and the main-loop catch in :func:`run_interactive` opens the
    navigator UI.  The non-``None`` form is reserved for future programmatic
    jumps (e.g. a hot-key keyed directly to a phase).
    """

    def __init__(self, target_phase: int | None = None,
                 target_qid: str | None = None) -> None:
        super().__init__()
        self.target_phase = target_phase
        self.target_qid = target_qid


def _input(hint: str) -> str:
    """Read one line at a ``hint ›`` prompt.

    Translates EOF / Ctrl-C / the ``:q`` family into an ``_Abort``, the
    ``:s`` family into a ``_Skip``, and the ``:b`` / ``:back`` / ``:nav``
    family into a ``_Navigate`` — so the caller's input loop never has to
    special-case those control words.  ``_Navigate`` is raised with no
    target; the main loop catches it and opens the question navigator.

    When ``_NAV_AVAILABLE`` is True (the default — every rule-based prompt)
    the rendered hint gets an inline ``:b back`` reminder so the user
    doesn't have to memorise the command from the banner alone.  The flag
    flips off in contexts where ``:b`` is silently ignored (LLM follow-ups,
    the navigator's own line-mode picker), so the prompt doesn't lie.
    """
    label = f"{hint} :b back" if _NAV_AVAILABLE else hint
    try:
        raw = input("  " + dim(f"{label} ›") + " ")
    except (EOFError, KeyboardInterrupt):
        print()
        raise _Abort()
    s = raw.strip()
    if s in (":q", ":quit", ":exit"):
        raise _Abort()
    if s in (":s", ":skip"):
        raise _Skip()
    if s in (":b", ":back", ":nav"):
        raise _Navigate()
    return s


def _err(msg: str) -> None:
    """Show a validation error; the caller then re-prompts the same question."""
    print("  " + red("✗ " + msg))


def _ok(value: Any) -> None:
    """Echo the accepted answer back, Claude-Code style."""
    print("  " + green("✓ ") + dim(str(value)))


def _read_bool(default: bool | None = None) -> bool:
    """Prompt for yes/no.  Empty input falls back to ``default`` when given."""
    hint = {True: "yes/no [Y/n]", False: "yes/no [y/N]", None: "yes/no [y/n]"}[default]
    while True:
        s = _input(hint).lower()
        if not s and default is not None:
            return default
        if s in ("y", "yes", "true", "1"):
            return True
        if s in ("n", "no", "false", "0"):
            return False
        _err("please answer y or n")


def _read_int(lo: int | None = None, hi: int | None = None,
              default: int | None = None) -> int:
    """Prompt for a whole number within an optional [lo, hi] range."""
    while True:
        s = _input("integer" + (f" [{default}]" if default is not None else ""))
        if not s and default is not None:
            return int(default)
        try:
            v = int(s)
        except ValueError:
            _err("not a whole number")
            continue
        if lo is not None and v < lo:
            _err(f"must be ≥ {lo}")
            continue
        if hi is not None and v > hi:
            _err(f"must be ≤ {hi}")
            continue
        return v


def _read_float(lo: float | None = None, hi: float | None = None,
                default: float | None = None, positive: bool = False) -> float:
    """Prompt for a number within an optional range.

    ``positive=True`` enforces > 0 — the engine rejects non-positive floats
    (height/weight fields), so we catch it here instead of on submit.
    """
    while True:
        s = _input("number" + (f" [{default}]" if default is not None else ""))
        if not s and default is not None:
            return float(default)
        try:
            v = float(s)
        except ValueError:
            _err("not a number")
            continue
        if positive and v <= 0:
            _err("must be greater than 0")
            continue
        if lo is not None and v < lo:
            _err(f"must be ≥ {lo}")
            continue
        if hi is not None and v > hi:
            _err(f"must be ≤ {hi}")
            continue
        return v


def _read_date(default: str | None = None, no_future: bool = False) -> str:
    """Prompt for an ISO date (YYYY-MM-DD).

    ``no_future=True`` matches the engine's ``datetime`` field rule, which
    rejects dates in the future.
    """
    while True:
        s = _input("date YYYY-MM-DD" + (f" [{default}]" if default else ""))
        if not s and default:
            return default
        try:
            parsed = date.fromisoformat(s)
        except ValueError:
            _err("expected an ISO date, e.g. 2020-01-31")
            continue
        if no_future and parsed > date.today():
            _err("must not be in the future")
            continue
        return s


def _read_choice_line(options: list[dict], *, default_id: str | None = None,
                      previous_value: str | None = None) -> str:
    """Line-buffered single-select fallback (used off-TTY or under ``--no-tui``).

    Accepts the 1-based list number, the exact option id, or a
    case-insensitive id/label match — whichever the user finds easier.
    When ``previous_value`` is supplied (after a back-edit), empty input
    keeps the previous answer; the prompt hint shows both the previous
    value and any positional default.
    """
    ids = [str(o.get("id", "?")) for o in options]
    # `previous_value` (post back-edit) takes precedence over `default_id`
    # for "what does Enter mean here?" — but we still surface both in the
    # hint so the user can tell them apart.
    enter_keeps = previous_value if previous_value is not None else default_id
    hint_bits: list[str] = []
    if previous_value is not None:
        hint_bits.append(f"previous: {previous_value}")
    elif default_id is not None:
        hint_bits.append(f"default: {default_id}")
    hint_suffix = f" [{', '.join(hint_bits)}, Enter to keep]" if hint_bits else ""
    while True:
        s = _input(f"pick 1-{len(options)}" + hint_suffix)
        if not s and enter_keeps is not None:
            return enter_keeps
        if s.isdigit():
            n = int(s)
            if 1 <= n <= len(options):
                return ids[n - 1]
            _err(f"pick a number between 1 and {len(options)}")
            continue
        if s in ids:
            return s
        low = s.lower()
        for o in options:
            if low in (str(o.get("id", "")).lower(), str(o.get("label", "")).lower()):
                return str(o.get("id"))
        _err("not a valid choice — type the list number or the exact id")


def _read_multi_choice_line(options: list[dict], *, optional: bool = True,
                            previous_value: list[str] | None = None) -> list[str]:
    """Line-buffered multi-select fallback.

    Comma- or space-separated 1-based numbers / option ids.  Empty input — or
    the word ``none`` — yields an empty list, except when ``previous_value``
    is supplied (after a back-edit), in which case empty input keeps the
    previous selection.  Duplicate picks are de-duplicated, preserving
    first-seen order.
    """
    ids = [str(o.get("id", "?")) for o in options]
    hint_suffix = ""
    if previous_value is not None:
        hint_suffix = f" [previous: {previous_value}, Enter to keep]"
    while True:
        s = _input("pick any (comma-separated), or Enter/'none' for none" + hint_suffix)
        if not s:
            # Empty input → keep previous if we have one; otherwise an empty
            # selection (matches the legacy contract for non-revisit prompts).
            return list(previous_value) if previous_value is not None else []
        if s.lower() in ("none", "-"):
            return []
        tokens = [t for t in s.replace(",", " ").split() if t]
        chosen: list[str] = []
        ok = True
        for t in tokens:
            if t.isdigit() and 1 <= int(t) <= len(options):
                cid = ids[int(t) - 1]
            elif t in ids:
                cid = t
            else:
                _err(f"invalid choice: {t!r}")
                ok = False
                break
            if cid not in chosen:
                chosen.append(cid)
        if ok:
            return chosen


def _read_choice(options: list[dict], default_id: str | None = None, *,
                 previous_value: str | None = None,
                 allow_skip: bool = False) -> str:
    """Single-select dispatcher: TUI menu on a TTY, line-buffered fallback off-TTY.

    The TUI path (``_read_choice_tui``) lets the user move a highlight with
    arrow keys; the fallback (``_read_choice_line``) prints a numbered list
    and reads a line of input.  Both honour ``previous_value`` (pre-fill
    after a back-edit) and return the same shape — the option id.

    ``allow_skip`` only matters in TUI mode (where ``s`` raises ``_Skip``);
    the line-input ``:s`` flows through ``_input`` regardless.
    """
    if _tui_available():
        return _read_choice_tui(
            options, default_id=default_id,
            previous_value=previous_value, allow_skip=allow_skip,
        )
    return _read_choice_line(
        options, default_id=default_id, previous_value=previous_value,
    )


def _read_multi_choice(options: list[dict], optional: bool = True, *,
                       previous_value: list[str] | None = None) -> list[str]:
    """Multi-select dispatcher: TUI checkbox menu on a TTY, line fallback off-TTY.

    Both paths return a list of selected ids in cursor-visit / first-toggled
    order — preserving the contract the engine submission code depends on.
    """
    if _tui_available():
        return _read_multi_choice_tui(
            options, optional=optional, previous_value=previous_value,
        )
    return _read_multi_choice_line(
        options, optional=optional, previous_value=previous_value,
    )


def _draw_menu(options: list[dict], cursor: int, *,
               multi: bool = False, checked: list[int] | None = None,
               footer: str) -> int:
    """Render an interactive menu and return the number of lines printed.

    The caller uses the line count to compute the cursor-up distance for the
    next redraw (``\\033[<N>F`` + ``\\033[J``).  Cursor row is bolded and
    prefixed with ``›``; in multi-select mode each row carries a ``[x]``/``[ ]``
    checkbox keyed by the ``checked`` index list.
    """
    checked_set = set(checked or [])
    lines = 0
    for i, opt in enumerate(options):
        oid = str(opt.get("id", "?"))
        label = str(opt.get("label", oid))
        is_cursor = (i == cursor)
        prefix = cyan(bold("›")) if is_cursor else " "
        if multi:
            box = (green("[x]") if i in checked_set else dim("[ ]")) + " "
        else:
            box = ""
        # Highlight the label on the cursor row; trailing id-in-parens stays dim.
        label_styled = cyan(bold(label)) if is_cursor else label
        tail = dim(f"  ({oid})") if label != oid else ""
        print(f"    {prefix} {box}{label_styled}{tail}")
        lines += 1
    print(footer)
    lines += 1
    return lines


def _erase_lines(n: int) -> None:
    """Cursor-up ``n`` lines, then clear everything from there to end of screen.

    Used to remove a TUI menu before returning control to the caller.  ``n``
    must match the line count returned by the most recent ``_draw_menu``.
    """
    if n <= 0:
        return
    sys.stdout.write(f"\033[{n}F\033[J")
    sys.stdout.flush()


def _read_choice_tui(
    options: list[dict],
    *,
    default_id: str | None = None,
    previous_value: str | None = None,
    allow_skip: bool = False,
) -> str:
    """Arrow-key single-select.  Returns the chosen option id.

    Key bindings:

      ↑ / k      move highlight up      (wraps around top↔bottom)
      ↓ / j      move highlight down
      Home/End   jump to first/last
      Enter      confirm the highlighted option
      Tab        open the question navigator  (raises ``_Navigate``)
      Esc / q    abort the session            (raises ``_Abort``)
      s          skip (only when ``allow_skip``; raises ``_Skip``)

    Initial highlight: ``previous_value`` (if it matches an option id) →
    ``default_id`` → first option.  On confirm the menu is erased so the
    caller's ``_ok()`` echo replaces it cleanly.
    """
    ids = [str(o.get("id", "?")) for o in options]
    if previous_value is not None and previous_value in ids:
        idx = ids.index(previous_value)
    elif default_id is not None and default_id in ids:
        idx = ids.index(default_id)
    else:
        idx = 0

    footer_bits = ["↑↓ move", "Enter confirm", "Tab navigator", "q cancel"]
    if allow_skip:
        footer_bits.append("s skip")
    footer = "    " + dim(" · ".join(footer_bits))
    if previous_value is not None:
        footer += dim(f"  (Enter keeps previous: {previous_value})")

    # Outcome captured inside the loop; raised/returned after we leave _raw_mode
    # and erase the menu, so the terminal is clean either way.
    chosen: str | None = None
    pending_exc: Exception | None = None
    n_lines = 0

    with _raw_mode():
        n_lines = _draw_menu(options, idx, multi=False, footer=footer)
        while True:
            try:
                key = read_key()
            except KeyboardInterrupt:
                pending_exc = _Abort()
                break
            if key in (KEY_UP, "k"):
                idx = (idx - 1) % len(options)
            elif key in (KEY_DOWN, "j"):
                idx = (idx + 1) % len(options)
            elif key == KEY_HOME:
                idx = 0
            elif key == KEY_END:
                idx = len(options) - 1
            elif key == KEY_ENTER:
                chosen = ids[idx]
                break
            elif key == KEY_TAB:
                pending_exc = _Navigate()
                break
            elif key in (KEY_ESC, "q"):
                pending_exc = _Abort()
                break
            elif key == "s" and allow_skip:
                pending_exc = _Skip()
                break
            else:
                # Any other key — ignore without redrawing.
                continue
            # Movement key landed here → redraw in place.
            _erase_lines(n_lines)
            n_lines = _draw_menu(options, idx, multi=False, footer=footer)

    _erase_lines(n_lines)
    if pending_exc is not None:
        raise pending_exc
    # ``chosen`` is guaranteed set on the ENTER branch.
    assert chosen is not None
    return chosen


def _read_multi_choice_tui(
    options: list[dict],
    *,
    optional: bool = True,
    default_ids: list[str] | None = None,
    previous_value: list[str] | None = None,
) -> list[str]:
    """Arrow-key multi-select with checkboxes.

    Key bindings:

      ↑ / k      move highlight up      (wraps around top↔bottom)
      ↓ / j      move highlight down
      Home/End   jump to first/last
      Space      toggle the highlighted row
      a          select all
      n          clear all
      Enter      confirm  (empty allowed iff ``optional``)
      Tab        open the question navigator  (raises ``_Navigate``)
      Esc / q    abort                         (raises ``_Abort``)

    Returns the chosen option ids in *first-toggled order* — preserving the
    contract the engine submission code depends on (matches the legacy
    ``_read_multi_choice_line`` behaviour).  Initial selection: ``previous_value``
    (if all ids are valid) → ``default_ids`` → empty.
    """
    ids = [str(o.get("id", "?")) for o in options]
    id_to_idx = {oid: i for i, oid in enumerate(ids)}

    # Initial chosen order — preserve incoming sequence.
    chosen_order: list[int] = []
    seed = previous_value if previous_value is not None else default_ids
    if seed:
        for oid in seed:
            if oid in id_to_idx and id_to_idx[oid] not in chosen_order:
                chosen_order.append(id_to_idx[oid])

    cursor = chosen_order[0] if chosen_order else 0

    footer_bits = [
        "↑↓ move", "Space toggle", "a all", "n none",
        "Enter confirm", "Tab navigator", "q cancel",
    ]
    footer = "    " + dim(" · ".join(footer_bits))
    if previous_value is not None:
        footer += dim(f"  (Enter keeps previous: {list(previous_value)})")

    pending_exc: Exception | None = None
    confirmed = False
    n_lines = 0

    with _raw_mode():
        n_lines = _draw_menu(
            options, cursor, multi=True, checked=chosen_order, footer=footer,
        )
        while True:
            try:
                key = read_key()
            except KeyboardInterrupt:
                pending_exc = _Abort()
                break
            redraw = False
            if key in (KEY_UP, "k"):
                cursor = (cursor - 1) % len(options); redraw = True
            elif key in (KEY_DOWN, "j"):
                cursor = (cursor + 1) % len(options); redraw = True
            elif key == KEY_HOME:
                cursor = 0; redraw = True
            elif key == KEY_END:
                cursor = len(options) - 1; redraw = True
            elif key == KEY_SPACE:
                if cursor in chosen_order:
                    chosen_order.remove(cursor)
                else:
                    chosen_order.append(cursor)
                redraw = True
            elif key == "a":
                # Select all in option order; preserve relative order for
                # already-selected items.
                for i in range(len(options)):
                    if i not in chosen_order:
                        chosen_order.append(i)
                redraw = True
            elif key == "n":
                chosen_order.clear()
                redraw = True
            elif key == KEY_ENTER:
                if not chosen_order and not optional:
                    # Required → ignore Enter with no selection.  We could
                    # flash an error, but the simpler signal is the
                    # un-changing checkboxes; the footer's "Enter confirm"
                    # speaks for itself.
                    continue
                confirmed = True
                break
            elif key == KEY_TAB:
                pending_exc = _Navigate()
                break
            elif key in (KEY_ESC, "q"):
                pending_exc = _Abort()
                break
            # any other key → ignore
            if redraw:
                _erase_lines(n_lines)
                n_lines = _draw_menu(
                    options, cursor, multi=True,
                    checked=chosen_order, footer=footer,
                )

    _erase_lines(n_lines)
    if pending_exc is not None:
        raise pending_exc
    assert confirmed
    return [ids[i] for i in chosen_order]


def _read_text(default: str | None = None, optional: bool = False) -> str:
    """Prompt for free text.  Empty input yields ``default`` (or "")."""
    if default:
        hint = f"text [{default}]"
    elif optional:
        hint = "text (optional, Enter to skip)"
    else:
        hint = "text"
    s = _input(hint)
    if not s:
        return default or ""
    return s


# ---------------------------------------------------------------------------
# Question rendering
# ---------------------------------------------------------------------------


def _show_question(q, *, index: int | None = None, total: int | None = None,
                   verbose: bool = False, skip_options: bool = False) -> None:
    """Print a question header: the text, its qid/type, and any choices.

    ``index``/``total`` annotate position within a bulk phase (e.g. ``[2/6]``).
    ``skip_options=True`` suppresses the static numbered option list — used
    when the TUI select readers are about to render the interactive menu
    themselves, so we don't paint the same options twice.
    """
    pos = f" [{index}/{total}]" if index is not None and total else ""
    print()
    print("  " + cyan(bold("❯ " + q.question)) + dim(pos))

    meta_bits = [q.qid, "type: " + q.question_type]
    if q.metadata and q.metadata.get("optional"):
        meta_bits.append("optional")
    print("    " + dim(" · ".join(meta_bits)))

    if q.image:
        print("    " + dim("image: " + str(q.image)))

    # Numbered option list for select / enum types.  When the id differs from
    # the label (e.g. symptom options: English id, Thai label) show both.
    if q.options and not skip_options:
        for i, opt in enumerate(q.options, 1):
            oid = str(opt.get("id", "?"))
            label = str(opt.get("label", oid))
            tail = "" if label == oid else dim(f"  ({oid})")
            print(f"      {dim(str(i) + '.')} {label}{tail}")

    # Sub-field list for free_text_with_fields.
    if q.fields:
        for f in q.fields:
            fid = f.get("id", "?")
            print("      " + dim("- ") + str(f.get("label", fid)) + dim(f"  ({fid})"))

    # Numeric bounds for number_range.
    if q.constraints:
        c = q.constraints
        rng = f"{c.get('min', '?')} – {c.get('max', '?')}"
        if c.get("step") is not None:
            rng += f", step {c['step']}"
        if c.get("default") is not None:
            rng += f", default {c['default']}"
        print("    " + dim("range: " + rng))

    if verbose and q.answer_schema:
        print("    " + dim("answer_schema: "
                           + json.dumps(q.answer_schema, ensure_ascii=False)))


def _read_yes_no_detail(q, *, previous_value: dict | None = None) -> dict:
    """Collect a ``yes_no_detail`` answer: ``{"answer": bool[, "detail": ...]}``.

    A "no" answer needs nothing more.  A "yes" answer may carry a detail
    payload: phase 6 (personal history) attaches structured ``detail_fields``
    metadata, so we prompt each sub-field by its type; phases 0 & 5 do not, so
    we fall back to an optional free-text note (the engine accepts a plain
    string — or no detail at all — for those).

    ``previous_value`` (after a back-edit) lets us pre-fill: ``["answer"]``
    becomes the yes/no default, and ``["detail"]`` is routed to the matching
    sub-prompts (dict keys for ``detail_fields`` mode, the whole string in
    free-note mode).
    """
    prev = previous_value if isinstance(previous_value, dict) else None
    prev_answer = prev.get("answer") if prev else None
    prev_detail = prev.get("detail") if prev else None

    if not _read_bool(default=prev_answer if prev_answer is not None else False):
        _ok("no")
        return {"answer": False}

    detail_fields = (q.metadata or {}).get("detail_fields")
    if detail_fields:
        detail: dict[str, Any] = {}
        prev_detail_dict = prev_detail if isinstance(prev_detail, dict) else {}
        for df in detail_fields:
            name = df.get("field_name_th") or df.get("key")
            print("    " + dim("· detail: " + str(name)))
            dtype = df.get("type")
            key = df["key"]
            prev_sub = prev_detail_dict.get(key)
            if dtype == "int":
                detail[key] = _read_int(default=prev_sub if isinstance(prev_sub, int) else None)
            elif dtype == "enum" and df.get("values"):
                opts = [{"id": v, "label": v} for v in df["values"]]
                detail[key] = _read_choice(
                    opts,
                    previous_value=prev_sub if isinstance(prev_sub, str) else None,
                )
            else:
                detail[key] = _read_text(
                    default=prev_sub if isinstance(prev_sub, str) else None,
                    optional=True,
                )
        result = {"answer": True, "detail": detail}
        _ok(result)
        return result

    # Free-text note path — preserve the previous string detail as the default.
    prev_note = prev_detail if isinstance(prev_detail, str) else None
    note = _read_text(default=prev_note, optional=True)
    result = {"answer": True}
    if note:
        result["detail"] = note
    _ok(result)
    return result


def read_answer(q, store: RulesetStore, *, index: int | None = None,
                total: int | None = None, verbose: bool = False) -> Any:
    """Render a single question and return the user's answer.

    Dispatches on ``question_type`` — this one function covers every
    user-facing type the engine emits, across both the demographic-style bulk
    phases (0, 1, 3, 5, 6) and the sequential phases (4, 7).  Phase 2 (symptom
    selection) is handled separately by :func:`read_symptom_selection`.
    """
    _show_question(q, index=index, total=total, verbose=verbose,
                   skip_options=_should_skip_static_options(q))
    qt = q.question_type
    schema = q.answer_schema or {}
    # After a back-edit, the engine injects the user's earlier answer into
    # ``q.metadata["previous_value"]`` so we can pre-fill it as the default
    # and let Enter mean "keep".  ``None`` everywhere else — pristine prompt.
    prev = (q.metadata or {}).get("previous_value")

    # --- ER yes/no checklists (phases 1 & 3) -------------------------------
    if qt == "yes_no":
        v = _read_bool(default=prev if isinstance(prev, bool) else False)
        _ok("yes" if v else "no")
        return v

    # --- Demographic-style field types (phases 0, 5, 6) --------------------
    if qt == "int":
        # Counts / years / ages — non-negative by domain.  Use the schema's
        # explicit minimum when present, otherwise floor at 0.
        v = _read_int(
            lo=schema.get("minimum", 0), hi=schema.get("maximum"),
            default=prev if isinstance(prev, int) else None,
        )
        _ok(v)
        return v

    if qt == "float":
        v = _read_float(
            positive=True,
            default=prev if isinstance(prev, (int, float)) else None,
        )
        _ok(v)
        return v

    if qt == "enum":
        if not q.options:
            v = _read_text(default=prev if isinstance(prev, str) else None)
            _ok(v)
            return v
        v = _read_choice(
            q.options,
            previous_value=prev if isinstance(prev, str) else None,
        )
        _ok(v)
        return v

    if qt == "from_yaml":
        # List-valued field (e.g. underlying diseases).  The payload usually
        # omits inline options for from_yaml, so fall back to the store's
        # underlying-disease list — that is exactly what the engine validates
        # the submitted names against.  An empty list is valid.
        options = q.options or [
            {"id": ud.name, "label": ud.name_th}
            for ud in store.underlying_diseases
        ]
        if not options:
            print("    " + dim("(no options available — submitting an empty list)"))
            _ok("(none)")
            return []
        v = _read_multi_choice(
            options, optional=True,
            previous_value=list(prev) if isinstance(prev, list) else None,
        )
        _ok(v or "(none)")
        return v

    if qt in ("date", "datetime"):
        v = _read_date(
            default=prev if isinstance(prev, str) else None,
            no_future=(qt == "datetime"),
        )
        _ok(v)
        return v

    if qt == "yes_no_detail":
        return _read_yes_no_detail(q, previous_value=prev if isinstance(prev, dict) else None)

    # --- Sequential question types (phases 4 & 7) --------------------------
    if qt == "free_text":
        v = _read_text(default=prev if isinstance(prev, str) else None)
        _ok(v or "(blank)")
        return v

    if qt == "free_text_with_fields":
        if not q.fields:
            v = _read_text(default=prev if isinstance(prev, str) else None)
            _ok(v)
            return v
        prev_dict = prev if isinstance(prev, dict) else {}
        result: dict[str, str] = {}
        for f in q.fields:
            fid = str(f["id"])
            label = str(f.get("label", fid))
            prev_sub = prev_dict.get(fid)
            # Mirror _input's prompt shape ("label ›"), inlining the
            # ``[previous: X]`` hint so Enter clearly means "keep".
            hint_label = "  " + label
            if isinstance(prev_sub, str) and prev_sub:
                hint_label += f" [{prev_sub}]"
            sval = _input(hint_label)
            if not sval and isinstance(prev_sub, str):
                sval = prev_sub
            result[fid] = sval
        _ok(result)
        return result

    if qt == "number_range":
        c = q.constraints or {}
        lo, hi, default = c.get("min"), c.get("max"), c.get("default")
        # `previous_value` overrides the constraint default when present.
        if isinstance(prev, (int, float)):
            default = prev
        # Use a float prompt when any bound looks like a float, else int.
        if isinstance(lo, float) or isinstance(hi, float) or isinstance(default, float):
            v: Any = _read_float(lo=lo, hi=hi, default=default)
        else:
            v = _read_int(lo=lo, hi=hi, default=default)
        _ok(v)
        return v

    if qt in ("single_select", "image_single_select"):
        if not q.options:
            v = _read_text(default=prev if isinstance(prev, str) else None)
            _ok(v)
            return v
        v = _read_choice(
            q.options,
            previous_value=prev if isinstance(prev, str) else None,
        )
        _ok(v)
        return v

    if qt in ("multi_select", "image_multi_select"):
        if not q.options:
            _ok("(none)")
            return []
        v = _read_multi_choice(
            q.options, optional=True,
            previous_value=list(prev) if isinstance(prev, list) else None,
        )
        _ok(v or "(none)")
        return v

    # --- str + any unexpected type fall back to free text ------------------
    v = _read_text(default=prev if isinstance(prev, str) else None)
    _ok(v)
    return v


def ask(q, store: RulesetStore, *, index: int | None = None,
        total: int | None = None, verbose: bool = False,
        allow_skip: bool = False) -> tuple[Any, bool]:
    """Render + read one question, returning ``(value, was_skipped)``.

    Wraps :func:`read_answer` with the ``:s`` skip protocol: when
    ``allow_skip`` is set (optional fields) a ``:s`` returns ``(None, True)``;
    otherwise the skip is rejected and the question is re-prompted.
    """
    while True:
        try:
            value = read_answer(q, store, index=index, total=total, verbose=verbose)
            return value, False
        except _Skip:
            if allow_skip:
                print("  " + dim("↳ skipped (optional)"))
                return None, True
            _err("this question can't be skipped — please answer it")


def read_bulk_fields(step, store: RulesetStore, *,
                     condition_fields: list | None = None,
                     verbose: bool = False) -> dict:
    """Collect a field-keyed bulk phase (0, 5, 6) — a dict keyed by field key.

    ``condition_fields``: for phase 0, the full ``DemographicField`` list.
    Phase 0 presents *every* demographic field, including conditional ones
    (unlike phases 5 & 6, whose conditional fields the engine pre-filters), so
    we must skip a conditional field whose condition is not met by the answers
    gathered so far in this same form — e.g. the pregnancy block for a male.
    Phases 5 & 6 pass ``None`` here (already filtered) but still honour the
    per-field ``optional`` flag.
    """
    field_by_key = {f.key: f for f in (condition_fields or [])}
    collected: dict[str, Any] = {}
    total = len(step.questions)

    for i, q in enumerate(step.questions, 1):
        key = q.metadata["key"]
        field = field_by_key.get(key)

        # Skip conditional fields that do not apply to this patient.  Print a
        # note so the walkthrough log still explains why the field is absent.
        if field is not None and field.condition and not _evaluate_field_condition(
            field.condition, collected
        ):
            print()
            print("  " + dim(f"· {q.question} ({key}) — skipped, condition not met"))
            continue

        optional = bool(q.metadata and q.metadata.get("optional"))
        value, skipped = ask(
            q, store, index=i, total=total, verbose=verbose, allow_skip=optional,
        )
        if not skipped:
            collected[key] = value

    return collected


def read_symptom_selection(step, preset_symptom: str | None, store: RulesetStore,
                           *, verbose: bool = False) -> dict:
    """Collect the phase-2 answer: ``{"primary_symptom", "secondary_symptoms"}``.

    When ``preset_symptom`` is given (via ``-s/--symptom``) and is a valid
    option, the primary-symptom prompt is skipped and the preset is used
    directly — otherwise the user picks it from the list like any other
    single-select.  Secondary symptoms are always prompted (optional).
    """
    answer: dict[str, Any] = {}
    for q in step.questions:
        # After a back-edit the engine pre-fills q.metadata["previous_value"]
        # with the user's earlier pick so we can offer "Enter to keep".
        prev = (q.metadata or {}).get("previous_value")
        if q.qid == "primary_symptom":
            _show_question(q, verbose=verbose,
                           skip_options=_should_skip_static_options(q))
            if preset_symptom is not None:
                valid = {str(o.get("id")) for o in (q.options or [])}
                if preset_symptom in valid:
                    print("  " + green("✓ ") + dim(f"{preset_symptom}  (preset via --symptom)"))
                    answer["primary_symptom"] = preset_symptom
                    continue
                _err(f"--symptom {preset_symptom!r} is not in the option list; pick manually")
            # The primary symptom is required — reject :s and re-prompt.
            while True:
                try:
                    pid = _read_choice(
                        q.options or [],
                        previous_value=prev if isinstance(prev, str) else None,
                    )
                    break
                except _Skip:
                    _err("the primary symptom is required — please pick one")
            _ok(pid)
            answer["primary_symptom"] = pid
        elif q.qid == "secondary_symptoms":
            _show_question(q, verbose=verbose,
                           skip_options=_should_skip_static_options(q))
            # Secondary symptoms are optional — both an empty pick and :s mean
            # "none".
            try:
                sids = _read_multi_choice(
                    q.options or [], optional=True,
                    previous_value=list(prev) if isinstance(prev, list) else None,
                )
            except _Skip:
                sids = []
            _ok(sids or "(none)")
            answer["secondary_symptoms"] = sids
        else:
            # Defensive: phase 2 only carries the two qids above, but if the
            # ruleset ever adds another, answer it generically rather than skip.
            value, _ = ask(q, store, verbose=verbose)
            answer[q.qid] = value
    return answer


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

_RULE = "═" * 64
_THIN = "─" * 64
_PHASE_RULE = "━" * 64


def banner(symptom_preset: str | None, args: argparse.Namespace) -> None:
    """Print the run header — config summary + the one usage hint that matters."""
    print(cyan(_RULE))
    print(cyan(bold("  INTERACTIVE PRESCREEN PIPELINE")))
    print(cyan(_RULE))
    print("  " + dim(f"symptom preset     : {symptom_preset or '(choose interactively)'}"))
    print("  " + dim(f"early termination  : "
                     f"{'DISABLED' if args.disable_early_termination else 'enabled'}"))
    print("  " + dim(f"question generator : {args.question_generation_backend}"))
    print("  " + dim(f"prediction backend : {args.prediction_backend}"))
    print("  " + dim("at any prompt: ':q' aborts the session · "
                     "':s' skips an optional field · "
                     "':b' (or Tab in a select menu) opens the question navigator"))


def phase_header(phase: int, name: str, mode: str) -> None:
    """Print a header marking the start of a new rule-based phase."""
    print()
    print(magenta(_PHASE_RULE))
    print(magenta(bold(f"  PHASE {phase}: {name}")) + "  " + dim(f"({mode})"))
    print(magenta(_PHASE_RULE))


def stage_header(name: str) -> None:
    """Print a header for a pipeline-level stage (LLM questioning, result)."""
    print()
    print(cyan(_RULE))
    print("  " + cyan(bold(name)))
    print(cyan(_RULE))


# ---------------------------------------------------------------------------
# Phase 7 (OPD) auto-eval replay
# ---------------------------------------------------------------------------


def log_opd_auto_eval_chain(store: RulesetStore, session_row: Any, *,
                            verbose: bool = False) -> None:
    """Replay and print the OPD auto-eval chain the engine ran internally.

    When phase 7 (OPD) is entirely conditional/filter questions, the engine
    resolves them without ever returning a user-facing step — so the
    interactive loop never shows phase 7.  This re-runs the same evaluation
    logic so the walkthrough log still shows what happened (which rule matched,
    what action it produced).
    """
    symptom = session_row.primary_symptom
    if not symptom:
        return

    # Rebuild the answers dict the engine evaluates against (skip __pending etc).
    answers: dict[str, Any] = {}
    for qid, entry in session_row.responses.items():
        if qid.startswith("__"):
            continue
        if isinstance(entry, dict) and "value" in entry:
            answers[qid] = entry["value"]
        else:
            answers[qid] = entry

    demographics = dict(session_row.demographics or {})
    # Derive age from date_of_birth if the explicit key is absent — age_filter
    # rules need it.
    if "age" not in demographics:
        dob_str = demographics.get("date_of_birth")
        if dob_str:
            try:
                dob = date.fromisoformat(str(dob_str))
                today = date.today()
                age = today.year - dob.year
                if (today.month, today.day) < (dob.month, dob.day):
                    age -= 1
                demographics["age"] = age
            except (ValueError, TypeError):
                pass

    evaluator = ConditionalEvaluator()

    try:
        first_qid = store.get_first_qid("opd", symptom)
    except KeyError:
        print("  " + dim("(no OPD decision tree for this symptom)"))
        return

    pending = [first_qid]
    step_num = 0

    while pending:
        qid = pending.pop(0)
        if qid in answers:
            continue
        try:
            question = store.get_question("opd", symptom, qid)
        except KeyError:
            continue

        if question.question_type not in AUTO_EVAL_TYPES:
            # A user-facing question — it would have been shown if reached.
            break

        action = evaluator.evaluate(question, answers, demographics)
        step_num += 1

        if action is None:
            desc = "no rule matched (skipped)"
        elif isinstance(action, GotoAction):
            desc = "goto → " + ", ".join(action.qid)
        elif isinstance(action, TerminateAction):
            depts = ", ".join(action.department or []) or "none"
            sevs = ", ".join(action.severity or []) or "none"
            desc = f"terminate (dept={depts}, sev={sevs})"
        else:
            desc = str(action.action)

        print(f"  {dim('auto ' + str(step_num) + '.')} {question.question} "
              + dim(f"({qid}) → {desc}"))

        if verbose and hasattr(question, "rules"):
            for i, rule in enumerate(question.rules, 1):
                preds = ", ".join(f"{p.qid} {p.op} {p.value}" for p in rule.when)
                print("           " + dim(f"rule {i}: when({preds})"))

        if action is None:
            continue
        if isinstance(action, GotoAction):
            new = [x for x in action.qid if x not in answers and x not in pending]
            pending[0:0] = new
        elif isinstance(action, TerminateAction):
            break


# ---------------------------------------------------------------------------
# Result + transcript rendering
# ---------------------------------------------------------------------------


def _fmt_answer(answer: Any) -> str:
    """Render an answer value compactly for the transcript."""
    if isinstance(answer, bool):
        return "yes" if answer else "no"
    if isinstance(answer, dict):
        return ", ".join(f"{k}={_fmt_answer(v)}" for k, v in answer.items())
    if isinstance(answer, list):
        return "[" + ", ".join(_fmt_answer(x) for x in answer) + "]"
    return str(answer)


def print_result(result: PipelineResult, store: RulesetStore) -> None:
    """Print the final departments / severity / diagnoses / reason block.

    Diagnoses are joined with their store-side metadata so the user sees
    ``d410  ความดันโลหิตสูง  (Hypertension)`` instead of an opaque
    ``d410``.  Disease IDs absent from ``store.diseases`` render with an
    ``(unknown disease)`` tail so the gap is visible at a glance (rather
    than printing a bare id that looks like normal output).
    """
    if result.departments:
        depts = ", ".join(
            f"{d.get('name', '?')} ({d.get('id', '?')})" for d in result.departments
        )
    else:
        depts = "(none)"
    print("  " + bold("departments : ") + depts)

    if result.severity:
        s = result.severity
        print("  " + bold("severity    : ") + f"{s.get('name', '?')} ({s.get('id', '?')})")
    else:
        print("  " + bold("severity    : ") + "(none)")

    if result.diagnoses:
        # Multi-line layout: one row per diagnosis with id + name(s).  Diseases
        # are ranked most-likely first by the prediction module — preserve
        # that order in the printed list.
        print("  " + bold("diagnoses   :"))
        for d in result.diagnoses:
            info = store.diseases.get(d.disease_id)
            if info is None:
                line = f"{d.disease_id}  " + dim("(unknown disease)")
            else:
                # Show Thai name (primary, what the patient would recognise)
                # followed by the English ``disease_name`` in dim parens —
                # mirrors the ``label (id)`` style used elsewhere in the
                # result block.  Skip the English half when it's the same as
                # the Thai (rare, but defensive).
                line = f"{d.disease_id}  {info.name_th}"
                if info.disease_name and info.disease_name != info.name_th:
                    line += dim(f"  ({info.disease_name})")
            print("    - " + line)
    else:
        print("  " + bold("diagnoses   : ") + "(none)")

    print("  " + bold("terminated  : ") + ("yes" if result.terminated_early else "no"))
    if result.reason:
        print("  " + bold("reason      : ") + result.reason)

    # Populated only on --disable-early-termination runs that hit (and skipped)
    # one or more termination conditions along the way.
    if result.skipped_terminations:
        print("  " + bold("skipped early terminations:"))
        for st in result.skipped_terminations:
            print("    " + dim(f"- phase {st.get('phase')} ({st.get('phase_name')}): "
                               f"{st.get('reason') or '(no reason)'}"))


def print_transcript(history: list[QAPair]) -> None:
    """Print the full chronological Q&A trail for the session."""
    if not history:
        return
    print()
    print(magenta(bold("  SESSION TRANSCRIPT")))
    print(magenta(_THIN))
    for qa in history:
        tag = f"P{qa.phase}" if qa.phase is not None else qa.source
        print("  " + dim(f"[{tag}] ") + str(qa.question))
        print("      " + green(_fmt_answer(qa.answer)))


# ---------------------------------------------------------------------------
# Question navigator — data layer
# ---------------------------------------------------------------------------
# These helpers build the list of revisitable past questions from
# ``pipeline.get_history``.  The TUI list view that consumes them lives further
# down (``_open_navigator``).

# Phase-name lookup used in navigator row labels.  Mirrors the engine's
# ``PHASE_NAMES`` constant; duplicated here so the navigator is purely a
# rendering concern and doesn't import an internal SDK constant.
_PHASE_NAMES_DISPLAY = {
    0: "Demographics", 1: "ER Critical", 2: "Symptom Selection",
    3: "ER Checklist", 4: "OLDCARTS", 5: "Past History",
    6: "Personal History", 7: "OPD",
}


@dataclass
class _NavigatorEntry:
    """One row in the question navigator list.

    For bulk phases (0–3, 5, 6) ``target_qid`` is always ``None`` — the engine
    only supports phase-level back-edit there — and the navigator collapses
    every answered qid in the phase to "jump back to phase N".  For sequential
    phases (4, 7) each qid is independently revisitable, so ``target_qid`` is
    the qid itself.  LLM follow-ups are emitted with ``revisitable=False`` and
    a ``disabled_reason`` so they show in the list but aren't pickable.
    """

    phase: int                 # source phase (or -1 for LLM rows)
    phase_name: str
    qid: str | None
    question: str              # display text (already truncated)
    answer_display: str        # _fmt_answer output (already truncated)
    target_phase: int          # what to hand to back_edit
    target_qid: str | None     # what to hand to back_edit (sequential only)
    revisitable: bool
    disabled_reason: str | None = None


def _current_qid_for_step(step) -> str | None:
    """Return the qid of the currently-prompted question for sequential phases.

    For phases 4 & 7 a ``QuestionsStep`` carries exactly one question; for bulk
    phases there's no single "current" qid — we identify the form by phase
    number alone (the engine rejects same-phase bulk re-entry as a no-op).
    """
    if getattr(step, "phase", None) in (4, 7) and len(step.questions) == 1:
        return step.questions[0].qid
    return None


def _truncate(s: str, max_chars: int) -> str:
    """Truncate ``s`` to ``max_chars`` with an ellipsis suffix when shortened."""
    if max_chars <= 1 or len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _build_navigator_entries(
    history: list[QAPair],
    store: RulesetStore,  # noqa: ARG001 - reserved for future per-qid lookups
    *,
    current_phase: int,
    current_qid: str | None,
) -> list[_NavigatorEntry]:
    """Build navigator rows from the live Q&A history.

    Disable rules:
      - **LLM follow-ups** are non-revisitable (the engine forbids back-edit
        once the ``llm_questioning`` stage starts).
      - **Current bulk phase** is non-revisitable (engine rejects same-phase
        no-op as ``ValueError``).
      - **Current sequential qid** is non-revisitable (it's the question we
        are already standing on).

    Truncation is sized to the current terminal width so long Thai questions
    don't wrap chaotically in the rendered list.
    """
    cols = max(40, min(shutil.get_terminal_size((80, 24)).columns, 100))
    # Reserve ~30 cols for the prefix/phase/qid/arrow/answer; remainder for question text.
    question_max = max(20, cols - 36)
    answer_max = max(12, cols // 4)

    entries: list[_NavigatorEntry] = []
    for qa in history:
        question_text = _truncate(str(qa.question), question_max)
        answer_text = _truncate(_fmt_answer(qa.answer), answer_max)

        if qa.source == "llm_generated":
            entries.append(_NavigatorEntry(
                phase=-1, phase_name="LLM", qid=None,
                question=question_text, answer_display=answer_text,
                target_phase=-1, target_qid=None,
                revisitable=False, disabled_reason="LLM follow-up",
            ))
            continue

        phase = qa.phase if qa.phase is not None else 0
        qid = qa.qid
        phase_name = _PHASE_NAMES_DISPLAY.get(phase, f"P{phase}")
        is_sequential = phase in (4, 7)

        if is_sequential:
            target_phase = phase
            target_qid = qid
            is_current = (phase == current_phase and qid == current_qid)
            disabled_reason = "current question" if is_current else None
        else:
            target_phase = phase
            target_qid = None  # bulk: back-edit reopens the whole phase
            is_current = (phase == current_phase)
            disabled_reason = "current phase" if is_current else None

        entries.append(_NavigatorEntry(
            phase=phase, phase_name=phase_name, qid=qid,
            question=question_text, answer_display=answer_text,
            target_phase=target_phase, target_qid=target_qid,
            revisitable=not is_current, disabled_reason=disabled_reason,
        ))
    return entries


def _draw_navigator(entries: list[_NavigatorEntry], cursor_idx: int,
                    footer: str) -> int:
    """Render the navigator list and return the line count for the next redraw.

    Disabled rows render in :func:`dim` with a leading ``·`` and never land
    under the cursor; revisitable rows use ``›`` for the highlight and a
    bolded label.  Each row has the shape ``[Phase] qid  question  →  answer``.
    """
    lines = 0
    print(cyan(bold("  jump back to a previous question") + dim("  (Esc cancels)")))
    lines += 1
    for i, e in enumerate(entries):
        tag = f"[{e.phase_name}]"
        qid_part = f"  {e.qid}" if e.qid else ""
        arrow = "  →  "
        if not e.revisitable:
            reason = f"  ({e.disabled_reason})" if e.disabled_reason else ""
            row = dim(f"  · {tag}{qid_part}  {e.question}{arrow}{e.answer_display}{reason}")
        else:
            is_cursor = (i == cursor_idx)
            prefix = cyan(bold("›")) if is_cursor else " "
            tag_styled = cyan(tag) if is_cursor else dim(tag)
            qid_styled = dim(qid_part)
            label_styled = cyan(bold(e.question)) if is_cursor else e.question
            ans_styled = dim(arrow + e.answer_display)
            row = f"  {prefix} {tag_styled}{qid_styled}  {label_styled}{ans_styled}"
        print(row)
        lines += 1
    print(footer)
    lines += 1
    return lines


def _open_navigator_tui(
    entries: list[_NavigatorEntry],
) -> tuple[int, str | None] | None:
    """TUI navigator — arrow keys + Enter; cursor skips disabled rows.

    Key bindings:

      ↑ / k      previous revisitable row  (skips disabled rows; wraps)
      ↓ / j      next revisitable row
      Home/End   first/last revisitable row
      Enter      jump to the highlighted row  → returns ``(target_phase, target_qid)``
      Esc / q    cancel                       → returns ``None``
    """
    revisitable_idx = [i for i, e in enumerate(entries) if e.revisitable]
    if not revisitable_idx:
        print()
        print("  " + dim("(nothing to revisit yet)"))
        return None

    # `cursor_pos` indexes into `revisitable_idx`; the entry-list cursor is
    # always `revisitable_idx[cursor_pos]`.  This automatically skips
    # disabled rows on every move.
    cursor_pos = 0
    footer = "    " + dim("↑↓ move · Enter jump · Esc cancel")

    chosen: tuple[int, str | None] | None = None
    pending_exc: Exception | None = None
    n_lines = 0

    with _raw_mode():
        n_lines = _draw_navigator(entries, revisitable_idx[cursor_pos], footer)
        while True:
            try:
                key = read_key()
            except KeyboardInterrupt:
                pending_exc = _Abort()
                break
            redraw = False
            if key in (KEY_UP, "k"):
                cursor_pos = (cursor_pos - 1) % len(revisitable_idx); redraw = True
            elif key in (KEY_DOWN, "j"):
                cursor_pos = (cursor_pos + 1) % len(revisitable_idx); redraw = True
            elif key == KEY_HOME:
                cursor_pos = 0; redraw = True
            elif key == KEY_END:
                cursor_pos = len(revisitable_idx) - 1; redraw = True
            elif key == KEY_ENTER:
                e = entries[revisitable_idx[cursor_pos]]
                chosen = (e.target_phase, e.target_qid)
                break
            elif key in (KEY_ESC, "q"):
                break  # chosen stays None
            # Tab is a no-op inside the navigator — we're already here.
            if redraw:
                _erase_lines(n_lines)
                n_lines = _draw_navigator(
                    entries, revisitable_idx[cursor_pos], footer,
                )

    _erase_lines(n_lines)
    if pending_exc is not None:
        raise pending_exc
    return chosen


def _open_navigator_line(
    entries: list[_NavigatorEntry],
) -> tuple[int, str | None] | None:
    """Line-buffered navigator — numbered list + line input.

    Used as the off-TTY fallback (piped stdin, ``--no-tui``, or ``--no-color``).
    Disabled rows are listed but can't be picked; an empty line or ``q``
    cancels.  Returns the same shape as ``_open_navigator_tui``.
    """
    revisitable_idx = [i for i, e in enumerate(entries) if e.revisitable]
    if not revisitable_idx:
        print()
        print("  " + dim("(nothing to revisit yet)"))
        return None

    print()
    print(cyan(bold("  jump back to a previous question") + dim("  (blank/q cancels)")))
    for i, e in enumerate(entries, 1):
        tag = f"[{e.phase_name}]"
        qid_part = f" {e.qid}" if e.qid else ""
        arrow = "  →  "
        if e.revisitable:
            print(
                f"  {dim(str(i) + '.')}  {tag}{qid_part}  {e.question}"
                + dim(arrow + e.answer_display)
            )
        else:
            reason = f"  ({e.disabled_reason})" if e.disabled_reason else ""
            print(dim(
                f"   --   {tag}{qid_part}  {e.question}{arrow}{e.answer_display}{reason}"
            ))

    # Suppress the inline ":b back" prompt hint while we're inside the
    # navigator — ``:b`` would recurse, so the prompt would lie about its
    # effect.  Restored on every exit path via try/finally.
    global _NAV_AVAILABLE
    nav_was = _NAV_AVAILABLE
    _NAV_AVAILABLE = False
    try:
        while True:
            # ``:b`` and ``:s`` are no-ops inside the navigator — catch them so
            # the user doesn't accidentally recurse.  ``:q`` still aborts the
            # whole session (propagate ``_Abort``).
            try:
                s = _input(f"pick 1-{len(entries)} (Enter/'q' cancels)")
            except (_Skip, _Navigate):
                continue
            if not s or s.lower() == "q":
                return None
            if s.isdigit():
                n = int(s)
                if 1 <= n <= len(entries):
                    target = entries[n - 1]
                    if target.revisitable:
                        return (target.target_phase, target.target_qid)
                    _err(f"that row isn't selectable: {target.disabled_reason}")
                    continue
                _err(f"pick a number between 1 and {len(entries)}")
                continue
            _err("type a row number or 'q' to cancel")
    finally:
        _NAV_AVAILABLE = nav_was


def _open_navigator(
    entries: list[_NavigatorEntry],
) -> tuple[int, str | None] | None:
    """Open the question navigator (TUI on a TTY, line-buffered fallback off-TTY).

    Returns ``(target_phase, target_qid)`` for ``pipeline.back_edit`` when the
    user picks a row, or ``None`` if they cancel — either way the main loop
    re-renders the (possibly reverted) step.
    """
    if _tui_available():
        return _open_navigator_tui(entries)
    return _open_navigator_line(entries)


# ---------------------------------------------------------------------------
# Main interactive loop
# ---------------------------------------------------------------------------


async def run_interactive(args: argparse.Namespace) -> None:
    """Drive the full pipeline, prompting the user for every answer."""
    # --- Load rulesets + wire up the pipeline with mocked DB + LLM ---------
    store = RulesetStore()
    store.load()

    preset_symptom = args.symptom
    if preset_symptom is not None and preset_symptom not in store.nhso_symptoms:
        available = ", ".join(sorted(store.nhso_symptoms))
        sys.stderr.write(
            f"error: unknown symptom {preset_symptom!r}.\n"
            f"available symptoms: {available}\n"
        )
        sys.exit(1)

    mock_repo = MockRepository()
    mock_db = AsyncMock()

    engine = PrescreenEngine(store)
    engine._repo = mock_repo

    pipeline = PrescreenPipeline(
        engine, store,
        generator=_build_generator(args.question_generation_backend),
        predictor=_build_predictor(store, args.prediction_backend),
    )
    pipeline._repo = mock_repo

    banner(preset_symptom, args)

    await pipeline.create_session(
        mock_db, user_id=USER_ID, session_id=SESSION_ID,
        disable_early_termination=args.disable_early_termination,
    )

    step = await pipeline.get_current_step(
        mock_db, user_id=USER_ID, session_id=SESSION_ID,
    )

    # --- Phases 0-7: adaptive loop -----------------------------------------
    # Each phase may trigger early termination, so we dispatch on the step type
    # after every submission rather than assuming a fixed phase sequence.
    current_phase: int | None = None
    seq_count = 0

    while isinstance(step, QuestionsStep):
        phase = step.phase

        if phase != current_phase:
            current_phase = phase
            mode = "bulk" if phase in _BULK_PHASES else "sequential"
            phase_header(phase, step.phase_name, mode)
            # When --disable-early-termination is on, a would-be termination on
            # the previous step is surfaced here instead of acted on.
            if step.skipped_termination is not None:
                st = step.skipped_termination
                print("  " + yellow(
                    f"⚠ skipped early termination from phase {st.phase} "
                    f"({st.phase_name}): {st.reason or '(no reason)'}"
                ))

        # --- Build the answer for this step ---
        # The collection + submit pair is wrapped in a try/except for two
        # control-flow exits:
        #   _Navigate — user asked to jump back to a previous question (Tab in
        #     a TUI menu, or ":b" at a line prompt).  We open the navigator,
        #     call back_edit, and let the while-loop pick up at the reverted
        #     step.  Any partial bulk-phase answers are discarded — the engine
        #     re-presents the phase from scratch with previous_value pre-fill.
        #   ValueError — engine rejected the submitted answer; we re-render
        #     the same phase so the user can fix and resubmit.
        try:
            if phase == 2:
                answer: Any = read_symptom_selection(
                    step, preset_symptom, store, verbose=args.verbose,
                )
            elif phase == 0:
                # Demographics — bulk, keyed by field key.  Pass the full
                # DemographicField list so conditional fields (the pregnancy
                # block, infant age-in-months) are skipped when they don't apply.
                answer = read_bulk_fields(
                    step, store, condition_fields=store.demographics,
                    verbose=args.verbose,
                )
            elif phase in (5, 6):
                # Past / personal history — bulk, keyed by field key.  The engine
                # has already filtered conditional fields for these phases.
                answer = read_bulk_fields(step, store, verbose=args.verbose)
            elif phase in _ER_PHASES and args.skip_er:
                # --skip-er: auto-answer every ER check "no" so the run never
                # terminates in the ER phases.
                answer = {q.qid: False for q in step.questions}
                print("  " + dim(
                    f"(--skip-er) auto-answered {len(answer)} ER question(s) 'no'"
                ))
            elif phase in _ER_PHASES:
                # Bulk ER checklists — submission dict keyed by qid.
                answer = {}
                total = len(step.questions)
                for i, q in enumerate(step.questions, 1):
                    value, _ = ask(q, store, index=i, total=total, verbose=args.verbose)
                    answer[q.qid] = value
            else:
                # Sequential phases (4 & 7) — exactly one question per step.
                value, _ = ask(step.questions[0], store, verbose=args.verbose)
                answer = value
                seq_count += 1

            # Submit.  The engine validates the payload and may reject it (e.g. a
            # value that slipped past the local checks); on rejection we re-render
            # the *same* phase rather than crashing the walkthrough.
            step = await pipeline.submit_answer(
                mock_db, user_id=USER_ID, session_id=SESSION_ID, value=answer,
            )
        except _Navigate as nav:
            # User asked to jump back.  When triggered from a prompt (the
            # usual case) ``nav.target_*`` is ``None`` and we open the
            # navigator chooser; if a future caller raises ``_Navigate`` with
            # a concrete target we use it directly.
            target_phase, target_qid = nav.target_phase, nav.target_qid
            if target_phase is None:
                history = await pipeline.get_history(
                    mock_db, user_id=USER_ID, session_id=SESSION_ID,
                )
                entries = _build_navigator_entries(
                    history, store,
                    current_phase=phase,
                    current_qid=_current_qid_for_step(step),
                )
                picked = _open_navigator(entries)
                if picked is None:
                    # Cancelled — re-render the current step from the top.
                    current_phase = None
                    continue
                target_phase, target_qid = picked
            try:
                step = await pipeline.back_edit(
                    mock_db, user_id=USER_ID, session_id=SESSION_ID,
                    target_phase=target_phase, target_qid=target_qid,
                )
            except ValueError as exc:
                # Engine refused the jump (e.g. same-phase no-op slipped past
                # the navigator's disable filter).  Stay put.
                print()
                print("  " + red(f"✗ can't jump there: {exc}"))
                print("  " + dim("staying on the current question..."))
                current_phase = None
                continue
            current_phase = None  # force phase-header reprint at the new position
            continue
        except ValueError as exc:
            print()
            print("  " + red(f"✗ the engine rejected this submission: {exc}"))
            print("  " + dim("let's re-enter this phase..."))
            # `step` is unchanged → the while-loop re-renders the same phase.
            # Reset current_phase so the phase header reprints as a visual cue.
            current_phase = None
            continue

    # --- Phase 7 may have been fully auto-evaluated (no user-facing step) ---
    if current_phase != 7:
        session_row = await mock_repo.get_by_user_and_session(
            mock_db, USER_ID, SESSION_ID,
        )
        if session_row is not None and session_row.current_phase >= 7:
            phase_header(7, "OPD", "auto-evaluated")
            log_opd_auto_eval_chain(store, session_row, verbose=args.verbose)

    # --- Post-rule-based: LLM questioning / result / early termination -----
    if isinstance(step, LLMQuestionsStep):
        stage_header("LLM QUESTIONING")
        llm_answers: list[LLMAnswer] = []
        # Suppress the inline ":b back" reminder for the duration of the LLM
        # loop — the engine forbids back-edit here so the prompt would lie.
        # ``global`` declaration is at function scope; restored in the
        # try/finally below.
        global _NAV_AVAILABLE
        _llm_nav_was = _NAV_AVAILABLE
        _NAV_AVAILABLE = False
        try:
            for i, question in enumerate(step.questions, 1):
                print()
                print("  " + cyan(bold(f"❯ [LLM Q{i}] {question}")))
                # ``:b`` here can't actually navigate (back_edit is rejected
                # once llm_questioning starts) — silently re-prompt instead of
                # letting ``_Navigate`` propagate.  ``:s`` is still honoured.
                while True:
                    try:
                        ans = _read_text()
                    except _Skip:
                        ans = ""
                    except _Navigate:
                        continue  # silently ignore — no navigator in LLM stage
                    break
                _ok(ans or "(blank)")
                llm_answers.append(LLMAnswer(question=question, answer=ans))
        finally:
            _NAV_AVAILABLE = _llm_nav_was
        result = await pipeline.submit_llm_answers(
            mock_db, user_id=USER_ID, session_id=SESSION_ID, answers=llm_answers,
        )
    elif isinstance(step, PipelineResult):
        # Pipeline skipped LLM questioning (e.g. --question_generation_backend
        # none) or went straight to a result.
        result = step
    elif isinstance(step, TerminationStep):
        # Engine-level early termination (e.g. an ER redirect) — wrap it in a
        # PipelineResult so the result block below is uniform.
        stage_header("EARLY TERMINATION")
        print("  " + yellow(
            f"terminated at phase {step.phase}: {step.reason or '(no reason)'}"
        ))
        result = PipelineResult(
            departments=step.departments,
            severity=step.severity,
            diagnoses=[],
            reason=step.reason,
            terminated_early=True,
        )
    else:
        print("  " + red(f"unexpected step type: {type(step).__name__}"))
        return

    # --- Final result + transcript -----------------------------------------
    stage_header("RESULT")
    print_result(result, store)

    history = await pipeline.get_history(
        mock_db, user_id=USER_ID, session_id=SESSION_ID,
    )
    print_transcript(history)

    print()
    print(cyan(_RULE))
    print("  " + dim(f"walkthrough complete · {seq_count} sequential question(s) answered"))
    print(cyan(_RULE))


def list_symptoms(store: RulesetStore) -> None:
    """Print all available NHSO symptoms and exit."""
    print("Available NHSO symptoms:")
    print()
    for i, (name, sym) in enumerate(sorted(store.nhso_symptoms.items()), 1):
        print(f"  {i:2d}. {name:<28s} ({sym.name_th})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactively walk through the PrescreenPipeline, "
                    "answering every question yourself.",
    )
    parser.add_argument(
        "-s", "--symptom",
        default=None,
        help="Preset the phase-2 primary symptom (skips that prompt). "
             "Use --list-symptoms to see the options.",
    )
    parser.add_argument(
        "--list-symptoms",
        action="store_true",
        help="List the available NHSO symptoms and exit.",
    )
    parser.add_argument(
        "--skip-er",
        action="store_true",
        help="Auto-answer the ER yes/no phases (1 & 3) 'no' instead of prompting.",
    )
    parser.add_argument(
        "--disable-early-termination",
        action="store_true",
        help="Run all 8 phases to completion. This is the only way the "
             "walkthrough reaches the LLM prediction + disease-reason stages — "
             "the rule-based trees otherwise terminate well before phase 7.",
    )
    parser.add_argument(
        "--question_generation_backend",
        choices=["sim", "none", "openai"],
        default="none",
        help="LLM follow-up question generator (default: sim — the in-process "
             "mock). 'none' disables the LLM questioning stage; 'openai' uses "
             "the real OpenAIQuestionGenerator (requires OPENAI_API_KEY or "
             "OPENROUTER_API_KEY in the environment / .env).",
    )
    parser.add_argument(
        "--prediction_backend",
        choices=["sim", "openai", "medgemma_prescreen"],
        default="medgemma_prescreen",
        help="Prediction module backend (default: sim — the in-process mock). "
             "'openai' uses the real OpenAIPredictionModule; "
             "'medgemma_prescreen' uses the real MedgemmaPredictionModule "
             "(requires VLLM_PREDICTOR_URL / VLLM_PREDICTOR_MODEL in the "
             "environment / .env).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show each question's answer_schema alongside it.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colours in the output.",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Force the line-buffered fallback even on a TTY (debug aid; "
             "independent of --no-color).  In line mode, select prompts read "
             "a numbered pick and ':b' / ':back' opens the question "
             "navigator instead of Tab.",
    )

    # --- Hidden test-harness flags (env-gated so they don't pollute --help) ---
    # Setting THAILLM_INTERACTIVE_DEBUG=1 reveals --debug-keys and --force-tui.
    # These exist purely to drive deterministic TUI smoke tests without a real
    # PTY: --debug-keys "DOWN,ENTER,SPACE" pre-populates the key queue that
    # ``read_key`` drains; --force-tui flips ``_USE_TUI`` on even off-TTY so the
    # raw-mode readers actually run.
    _debug_mode = os.environ.get("THAILLM_INTERACTIVE_DEBUG") == "1"
    if _debug_mode:
        parser.add_argument(
            "--debug-keys", default=None,
            help="(debug) comma-separated key tokens to feed to read_key() "
                 "in order — e.g. 'DOWN,DOWN,ENTER'.  Accepts the KEY_* "
                 "names or single characters.",
        )
        parser.add_argument(
            "--force-tui", action="store_true",
            help="(debug) force _USE_TUI=True even when stdin/stdout aren't "
                 "TTYs.  Combine with --debug-keys to drive the TUI in tests.",
        )
    args = parser.parse_args()

    # Finalise colour + TUI gating before any output is produced.  Both
    # require an interactive TTY; the TUI additionally needs ``--no-color``
    # to be off (cursor escapes share the SGR-support assumption colour
    # styling needs).
    global _USE_COLOR, _USE_TUI
    _USE_COLOR = sys.stdout.isatty() and not args.no_color
    _USE_TUI = (not args.no_tui) and sys.stdin.isatty() and sys.stdout.isatty()

    # Test-harness overrides (only meaningful when THAILLM_INTERACTIVE_DEBUG=1
    # made the flags visible above).  --force-tui flips both _USE_TUI and
    # _USE_COLOR on so the TUI readers actually fire even with piped
    # stdin/stdout (necessary for deterministic harness runs).
    if _debug_mode:
        if getattr(args, "force_tui", False):
            _USE_TUI = True
            _USE_COLOR = True
        if getattr(args, "debug_keys", None):
            for token in args.debug_keys.split(","):
                token = token.strip()
                if token:
                    _DEBUG_KEY_QUEUE.append(token)

    if args.list_symptoms:
        store = RulesetStore()
        store.load()
        list_symptoms(store)
        return

    try:
        asyncio.run(run_interactive(args))
    except _Abort:
        print()
        print(yellow("  session aborted by user"))
        sys.exit(130)
    except KeyboardInterrupt:
        print()
        print(yellow("  interrupted"))
        sys.exit(130)


if __name__ == "__main__":
    main()
