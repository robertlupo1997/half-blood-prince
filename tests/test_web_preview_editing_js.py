"""Node.js-based execution tests for the annotation editing JS handlers.

These tests extract the actual function bodies from the generated HTML,
combine them with a minimal DOM stub, and run assertions under Node.js.
This proves the editing logic executes correctly — something a static
regex test cannot do.

Skipped automatically when Node.js is not on PATH.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from halfblood.models import AnnotatedPage, Annotation, AnnotationPlan, AnnotationType
from halfblood.web_preview import _render

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plan() -> AnnotationPlan:
    return AnnotationPlan(
        title="Advanced Potion-Making",
        prince_persona="the Half-Blood Prince",
        pages=[
            AnnotatedPage(
                page_number=1,
                original_text="Crush the sopophorous bean. Add the powdered root slowly.",
                annotations=[
                    Annotation(
                        page=1,
                        target_text="Crush the sopophorous bean",
                        annotation_type=AnnotationType.CORRECTION,
                        content="Crush, do not cut.",
                        confidence=0.9,
                        position="margin_right",
                    ),
                    Annotation(
                        page=1,
                        target_text="Add the powdered root",
                        annotation_type=AnnotationType.SHORTCUT,
                        content="Skip this entirely.",
                        confidence=0.7,
                        position="margin_left",
                    ),
                ],
            )
        ],
    )


def _main_script() -> str:
    """Return the main (last) <script> block from the rendered preview."""
    html, _ = _render(_plan(), None)
    matches = list(re.finditer(r"<script>(.*?)</script>", html, re.DOTALL))
    return matches[-1].group(1)


def _extract_function(src: str, name: str) -> str:
    """Extract a function declaration by brace-depth counting."""
    pattern = f"function {name}("
    start = src.find(pattern)
    if start == -1:
        return ""
    brace_start = src.index("{", start)
    depth = 0
    for i in range(brace_start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    return ""


def _run_js(js: str, timeout: int = 15) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    assert node, "node not on PATH"
    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
        f.write(js)
        fpath = f.name
    try:
        return subprocess.run(
            [node, fpath],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        Path(fpath).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def node() -> str:
    n = shutil.which("node")
    if not n:
        pytest.skip("node not available")
    return n


@pytest.fixture(scope="module")
def script() -> str:
    return _main_script()


# ---------------------------------------------------------------------------
# Syntax check
# ---------------------------------------------------------------------------


class TestNodeCheck:
    def test_extracted_script_passes_node_check(self, node: str) -> None:
        """A JS syntax error is invisible to all pytest tests — must check here."""
        script = _main_script()
        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
            f.write(script)
            fpath = f.name
        try:
            result = subprocess.run(
                [node, "--check", fpath],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert result.returncode == 0, (
                f"node --check failed:\n{result.stderr}"
            )
        finally:
            Path(fpath).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# DOM-stub harness: edit / delete / reposition / export
# ---------------------------------------------------------------------------

_DOM_STUB = """\
"use strict";
var removedNodes = [];
var bookTextHTML = '<mark data-ann-id="a0">Crush text</mark> rest';
var connectorEl = { remove: function() { removedNodes.push("connector:a0"); } };
var noteTextEl = { textContent: "Crush, do not cut.", style: {}, _display: "" };
var noteEl = {
  _removed: false, _movedToLeft: false, _movedToRight: false,
  remove: function() { this._removed = true; removedNodes.push("note:a0"); },
  querySelector: function(sel) { return (sel === ".note-text") ? noteTextEl : null; },
  appendChild: function() {},
  removeChild: function() {},
};
var markEl = {
  _replaced: false,
  textContent: "Crush text",
  replaceWith: function(node) {
    this._replaced = true;
    bookTextHTML = node.textContent || "";
  },
};
var createdElements = [];
global.document = {
  querySelector: function(sel) {
    return (sel.indexOf("a0") !== -1) ? noteEl : null;
  },
  querySelectorAll: function() { return []; },
  createElement: function(tag) {
    var el = {
      tagName: tag, type: "", className: "", rows: 0,
      get value() { return this._val || ""; },
      set value(v) { this._val = v; },
      textContent: "",
      style: { display: "" },
      _listeners: {},
      setAttribute: function() {},
      focus: function() {},
      appendChild: function() {},
      removeChild: function() {},
      addEventListener: function(ev, fn) { this._listeners[ev] = fn; },
    };
    createdElements.push(el);
    return el;
  },
  createTextNode: function(t) { return { textContent: t }; },
  execCommand: function() { return false; },
  body: { appendChild: function(){}, removeChild: function(){} },
};
global.requestAnimationFrame = function(fn) { fn(); };
global.window = {};
global.CSS = null;

var DATA = {
  pages: [{
    number: 1,
    annotations: [
      { id: "a0", content: "Crush, do not cut.", position: "margin_right",
        type: "correction", matched: true },
      { id: "a1", content: "Skip this entirely.", position: "margin_left",
        type: "shortcut", matched: false },
    ],
    html: bookTextHTML,
  }],
  totals: { annotations: 2, matched: 1 },
};
var state = {
  idx: 0, editingId: null,
  leftItems: [{ ann: DATA.pages[0].annotations[1], el: {} }],
  rightItems: [{ ann: DATA.pages[0].annotations[0], el: noteEl }],
};
var els = {
  bookText: {
    get innerHTML() { return bookTextHTML; },
    set innerHTML(v) { bookTextHTML = v; },
    querySelector: function(sel) {
      return (sel.indexOf("a0") !== -1) ? markEl : null;
    },
  },
  marginLeft:  { appendChild: function(el) { el._movedToLeft  = true; } },
  marginRight: { appendChild: function(el) { el._movedToRight = true; } },
  connectorLayer: {
    innerHTML: "",
    querySelector: function(sel) {
      return (sel.indexOf("a0") !== -1) ? connectorEl : null;
    },
  },
  indicator: { textContent: "" },
};

// Stub doLayout so we don't need layoutMargin/drawConnectors in scope.
function doLayout() {}
"""

_ASSERTIONS = """\
var PASS = 0, FAIL = 0;
function assert(label, cond) {
  if (cond) { console.log("PASS:", label); PASS++; }
  else       { console.log("FAIL:", label); FAIL++; }
}

// --- delete ---
var before = DATA.pages[0].annotations.length;
deleteAnnotation("a0");
assert("delete: annotation removed from DATA",
  DATA.pages[0].annotations.length === before - 1);
assert("delete: remaining annotation is a1",
  DATA.pages[0].annotations[0].id === "a1");
assert("delete: note element removed", noteEl._removed);
assert("delete: mark unwrapped", markEl._replaced);
assert("delete: connector removed",
  removedNodes.some(function(n){ return n === "connector:a0"; }));
assert("delete: rightItems emptied", state.rightItems.length === 0);
assert("delete: totals.annotations decremented", DATA.totals.annotations === 1);

// --- reposition ---
DATA.pages[0].annotations = [
  { id: "a0", content: "Crush, do not cut.", position: "margin_left",
    type: "correction", matched: true },
];
state.leftItems = [{ ann: DATA.pages[0].annotations[0], el: noteEl }];
state.rightItems = [];
noteEl._movedToLeft = false; noteEl._movedToRight = false;

repositionAnnotation("a0");
assert("reposition: position toggled to margin_right",
  DATA.pages[0].annotations[0].position === "margin_right");
assert("reposition: noteEl moved to marginRight", noteEl._movedToRight);
assert("reposition: item in rightItems",
  state.leftItems.length === 0 && state.rightItems.length === 1);

repositionAnnotation("a0");
assert("reposition: toggled back to margin_left",
  DATA.pages[0].annotations[0].position === "margin_left");

// --- startEdit / save ---
DATA.pages[0].annotations = [
  { id: "a0", content: "Crush, do not cut.", position: "margin_right",
    type: "correction", matched: true },
];
noteTextEl.textContent = "Crush, do not cut.";
noteTextEl.style.display = "";
state.editingId = null;
createdElements = [];

startEdit("a0");
assert("edit: editingId set", state.editingId === "a0");
assert("edit: noteText hidden", noteTextEl.style.display === "none");

var ta = createdElements.find(function(e){ return e.tagName === "textarea"; });
var saveBtn = createdElements.find(function(e){
  return e.className && e.className.indexOf("save") !== -1; });
assert("edit: textarea created", ta !== undefined);
assert("edit: save button created", saveBtn !== undefined);

if (ta) ta.value = "edited content";
if (saveBtn && saveBtn._listeners.click) {
  saveBtn._listeners.click({ stopPropagation: function(){} });
}
assert("edit: editingId cleared after save", state.editingId === null);
assert("edit: DATA updated", DATA.pages[0].annotations[0].content === "edited content");
assert("edit: DOM text updated", noteTextEl.textContent === "edited content");
assert("edit: noteText display restored", noteTextEl.style.display === "");

// --- double-open guard ---
state.editingId = null;
createdElements = [];
startEdit("a0");
var c1 = createdElements.length;
startEdit("a0"); // blocked
assert("double-open: second startEdit blocked", createdElements.length === c1);

// --- copy-json reflects edit ---
var parsed = JSON.parse(JSON.stringify(DATA, null, 2));
assert("copy-json: exported content is edited value",
  parsed.pages[0].annotations[0].content === "edited content");

// --- cancel ---
state.editingId = null;
noteTextEl.style.display = "";
createdElements = [];
startEdit("a0");
var cancelBtn = createdElements.find(function(e){
  return e.className && e.className.indexOf("cancel") !== -1; });
assert("cancel: cancel button created", cancelBtn !== undefined);
if (cancelBtn && cancelBtn._listeners.click) {
  cancelBtn._listeners.click({ stopPropagation: function(){} });
}
assert("cancel: editingId cleared", state.editingId === null);
assert("cancel: content NOT changed", DATA.pages[0].annotations[0].content === "edited content");
assert("cancel: display restored", noteTextEl.style.display === "");

// --- delete while editing: editingId must not stay wedged ---
// Re-arm a fresh page with a matched annotation and a second unmatched one.
DATA.pages[0].annotations = [
  { id: "a0", content: "Crush, do not cut.", position: "margin_right",
    type: "correction", matched: true },
  { id: "a1", content: "Skip this entirely.", position: "margin_left",
    type: "shortcut", matched: false },
];
DATA.totals = { annotations: 2, matched: 1 };
state.leftItems = [{ ann: DATA.pages[0].annotations[1], el: {} }];
state.rightItems = [{ ann: DATA.pages[0].annotations[0], el: noteEl }];
noteEl._removed = false;
markEl._replaced = false;
noteTextEl.style.display = "";
state.editingId = null;
createdElements = [];

startEdit("a0");
assert("wedge: editingId set before delete", state.editingId === "a0");
// Simulate clicking the delete button while the textarea is open
deleteAnnotation("a0");
assert("wedge: editingId cleared by delete", state.editingId === null);
assert("wedge: annotation removed from DATA", DATA.pages[0].annotations.length === 1);
// Now a second note should be editable — not silently blocked
createdElements = [];
// Temporarily override querySelector so a1's note lookup succeeds
var _origQS = document.querySelector;
document.querySelector = function(sel) {
  return (sel.indexOf("a1") !== -1) ? noteEl : null;
};
// Also fix noteEl so it hasn't been "removed"
noteEl._removed = false;
startEdit("a1");
assert("wedge: startEdit on a1 works after wedge cleared",
  state.editingId === "a1");
document.querySelector = _origQS;
state.editingId = null;

// --- totals.matched decrements on matched-annotation delete ---
DATA.pages[0].annotations = [
  { id: "a0", content: "Crush.", position: "margin_right",
    type: "correction", matched: true },
  { id: "a1", content: "Skip.", position: "margin_left",
    type: "shortcut", matched: false },
];
DATA.totals = { annotations: 2, matched: 1 };
state.leftItems = [{ ann: DATA.pages[0].annotations[1], el: {} }];
state.rightItems = [{ ann: DATA.pages[0].annotations[0], el: noteEl }];
noteEl._removed = false; markEl._replaced = false;

deleteAnnotation("a0");
assert("matched-delete: totals.matched decremented",
  DATA.totals.matched === 0);
assert("matched-delete: totals.annotations decremented",
  DATA.totals.annotations === 1);

// Deleting an unmatched annotation must NOT decrement totals.matched
DATA.pages[0].annotations = [
  { id: "a1", content: "Skip.", position: "margin_left",
    type: "shortcut", matched: false },
];
DATA.totals = { annotations: 1, matched: 0 };
state.leftItems = [{ ann: DATA.pages[0].annotations[0], el: {} }];
state.rightItems = [];
deleteAnnotation("a1");
assert("unmatched-delete: totals.matched stays 0",
  DATA.totals.matched === 0);

console.log("Results:", PASS, "passed,", FAIL, "failed");
if (FAIL > 0) process.exit(1);
"""


class TestEditingHandlers:
    def test_all_handlers_execute_correctly(self, node: str, script: str) -> None:
        """Run edit / delete / reposition / export under a DOM stub."""
        fn_cssEscape = _extract_function(script, "cssEscape")
        fn_delete = _extract_function(script, "deleteAnnotation")
        fn_repos = _extract_function(script, "repositionAnnotation")
        fn_edit = _extract_function(script, "startEdit")

        assert fn_cssEscape, "cssEscape function not found in generated script"
        assert fn_delete, "deleteAnnotation function not found in generated script"
        assert fn_repos, "repositionAnnotation function not found in generated script"
        assert fn_edit, "startEdit function not found in generated script"

        harness = (
            _DOM_STUB
            + "\n"
            + fn_cssEscape
            + "\n"
            + fn_delete
            + "\n"
            + fn_repos
            + "\n"
            + fn_edit
            + "\n"
            + _ASSERTIONS
        )

        result = _run_js(harness)
        print(result.stdout)  # captured in pytest -s, always shown on failure
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)

        assert result.returncode == 0, (
            f"Harness failed:\n{result.stdout}\n{result.stderr}"
        )
        # All individual lines must be PASS
        for line in result.stdout.splitlines():
            if line.startswith("FAIL:"):
                pytest.fail(f"Harness assertion failed: {line}")
