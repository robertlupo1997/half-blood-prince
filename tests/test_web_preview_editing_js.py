"""Node.js-based execution tests for the annotation editing JS handlers.

These tests extract the actual function bodies from the generated HTML,
combine them with a geometry-aware DOM stub, and run assertions under Node.js.
This proves the editing logic — including the real doLayout / layoutMargin /
drawConnectors call chain — executes correctly and produces geometrically
correct connector paths.  A static regex or Python-side test cannot do this.

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
# DOM-stub harness: edit / delete / reposition / export / connector geometry
#
# Design notes:
#
#   - noteEl tracks which margin it is in via ._side ("left" / "right").
#     getBoundingClientRect() returns left-column or right-column coordinates
#     accordingly.  els.marginLeft.appendChild / els.marginRight.appendChild
#     update ._side so the geometry automatically reflects the live position.
#
#   - connectorChildren is a persistent ordered list that mirrors the live DOM
#     children of connectorLayer.  doLayout clears it via the innerHTML=""
#     setter; drawConnectors appends new SVG path objects; deleteAnnotation's
#     conn.remove() splices individual entries.  Seeding a stale entry and
#     then asserting it is gone after repositionAnnotation proves that the
#     innerHTML="" clear actually fires.
#
#   - No function in the doLayout call tree is stubbed.  bindHover is included
#     verbatim; its event handlers only register (never fire) under the stub,
#     so their references to state.hoveredId / state.lockedIds are inert.
#
#   - a1El replaces bare {} for the a1 annotation element: real doLayout
#     iterates unanchored items and sets el.style.top / reads el.offsetHeight,
#     so a plain object would TypeError.
# ---------------------------------------------------------------------------

_DOM_STUB = """\
"use strict";

// === tracked side-effects ===
var removedNodes = [];
var bookTextHTML = '<mark data-ann-id="a0">Crush text</mark> rest';
var noteTextEl = { textContent: "Crush, do not cut.", style: {}, _display: "" };

// === geometry constants ===
// mark      : getBoundingClientRect() → { left: 300, right: 500, top: 100, height: 20 }
// frame     : getBoundingClientRect() → { left: 100, top: 0 }
// marginLeft: getBoundingClientRect() → { left: 0, top: 0 }
// marginRight:getBoundingClientRect() → { left: 800, top: 0 }
//
// noteEl.getBoundingClientRect() is STYLE-DRIVEN:
//   The top is derived from noteEl.style.top so layoutMargin's position
//   computation is observable.  (If layoutMargin never sets style.top the
//   top falls back to 0, producing wrong fromY — test goes RED.)
// note left : { left: 10,  right: 90,  top: parseFloat(style.top)||0, height: 30 }
// note right: { left: 910, right: 990, top: parseFloat(style.top)||0, height: 30 }
//
// layoutMargin sets style.top = (markTop - marginTop + markH/2 - noteH/2)
//   = 100 - 0 + 10 - 15 = 95 px  (for our anchored/matched note)
// Derived connector coordinates — see geometry section in _ASSERTIONS.

// === connectorChildren: mirrors connectorLayer DOM children ===
// doLayout sets connectorLayer.innerHTML = "" → setter calls connectorChildren.length = 0.
// drawConnectors calls connectorLayer.appendChild(path) → push to list.
// deleteAnnotation calls conn.remove() → splice from list.
var connectorChildren = [];

// === noteEl: element for annotation a0 ===
var noteEl = {
  _removed: false, _movedToLeft: false, _movedToRight: false,
  _side: "right",      // current margin — drives getBoundingClientRect
  offsetHeight: 30,
  style: { top: "", display: "" },
  remove: function() { this._removed = true; removedNodes.push("note:a0"); },
  querySelector: function(sel) { return (sel === ".note-text") ? noteTextEl : null; },
  appendChild: function() {},
  removeChild: function() {},
  getBoundingClientRect: function() {
    // Derive top from style.top so layoutMargin's output is observable.
    // Both margins have getBoundingClientRect().top = 0, so margin-relative
    // top equals absolute top in the stub's coordinate system.
    var absTop = parseFloat(this.style.top) || 0;
    return this._side === "left"
      ? { left: 10,  right: 90,  top: absTop, bottom: absTop + 30, height: 30 }
      : { left: 910, right: 990, top: absTop, bottom: absTop + 30, height: 30 };
  },
  classList: {
    contains: function() { return false; },
    toggle: function() {},
    add: function() {},
    remove: function() {},
  },
  addEventListener: function() {},
};

// === a1El: minimal element for annotation a1 (unmatched, always left) ===
// doLayout iterates unanchored items and accesses el.style.top / el.offsetHeight.
// getBoundingClientRect is style-driven for consistency (a1 is never anchored so
// no connector geometry depends on it, but the derivation stays honest).
var a1El = {
  style: { top: "" },
  offsetHeight: 30,
  getBoundingClientRect: function() {
    var absTop = parseFloat(this.style.top) || 0;
    return { left: 10, right: 90, top: absTop, bottom: absTop + 30, height: 30 };
  },
  classList: {
    contains: function() { return false; },
    toggle: function() {},
    add: function() {},
    remove: function() {},
  },
  addEventListener: function() {},
};

// === markEl: <mark> element for a0 in bookText ===
var markEl = {
  _replaced: false,
  textContent: "Crush text",
  getBoundingClientRect: function() {
    return { left: 300, right: 500, top: 100, bottom: 120, height: 20 };
  },
  replaceWith: function(node) {
    this._replaced = true;
    bookTextHTML = node.textContent || "";
  },
};

// Seed the initial connector for a0 so deleteAnnotation("a0") can remove it.
// Its remove() pushes "connector:a0" to removedNodes for the existing assertion.
var initialConnectorA0 = {
  dataset: { annId: "a0" },
  remove: function() {
    removedNodes.push("connector:a0");
    var i = connectorChildren.indexOf(this);
    if (i !== -1) connectorChildren.splice(i, 1);
  },
};
connectorChildren.push(initialConnectorA0);

// === document ===
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
  createElementNS: function(ns, tag) {
    // Creates a trackable SVG path element.
    var attrs = {};
    var path = {
      _attrs: attrs,
      dataset: {},
      style: {},
      setAttribute: function(name, val) { attrs[name] = val; },
      getAttribute: function(name) { return attrs[name]; },
      // getTotalLength() is not supported in the stub; drawConnectors catches the throw.
      getTotalLength: function() { throw new Error("not supported in DOM stub"); },
      addEventListener: function() {},
      remove: function() {
        var i = connectorChildren.indexOf(this);
        if (i !== -1) connectorChildren.splice(i, 1);
      },
    };
    return path;
  },
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
  idx: 0, editingId: null, query: null,
  hiddenTypes: new Set(), hoveredId: null, lockedIds: new Set(),
  leftItems:  [{ ann: DATA.pages[0].annotations[1], el: a1El  }],
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
  marginLeft: {
    getBoundingClientRect: function() { return { left: 0, top: 0 }; },
    appendChild: function(el) {
      el._movedToLeft = true;
      if (el === noteEl) noteEl._side = "left";
    },
  },
  marginRight: {
    getBoundingClientRect: function() { return { left: 800, top: 0 }; },
    appendChild: function(el) {
      el._movedToRight = true;
      if (el === noteEl) noteEl._side = "right";
    },
  },
  pageFrame: {
    getBoundingClientRect: function() { return { left: 100, top: 0 }; },
  },
  connectorLayer: {
    get innerHTML() { return ""; },
    // Clearing innerHTML empties the connector list — mirrors real DOM behaviour.
    set innerHTML(v) { if (v === "") connectorChildren.length = 0; },
    querySelector: function(sel) {
      var m = sel.match(/data-ann-id="([^"]+)"/);
      if (!m) return null;
      var id = m[1];
      for (var i = 0; i < connectorChildren.length; i++) {
        if (connectorChildren[i].dataset.annId === id) return connectorChildren[i];
      }
      return null;
    },
    appendChild: function(p) { connectorChildren.push(p); },
  },
  indicator: { textContent: "" },
};
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
state.leftItems  = [{ ann: DATA.pages[0].annotations[1], el: a1El  }];
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
state.leftItems  = [{ ann: DATA.pages[0].annotations[1], el: a1El  }];
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
state.leftItems  = [{ ann: DATA.pages[0].annotations[0], el: a1El }];
state.rightItems = [];
deleteAnnotation("a1");
assert("unmatched-delete: totals.matched stays 0",
  DATA.totals.matched === 0);

// ====================================================================
// --- connector geometry: repositioning draws on the correct side ---
//
// Expected coordinates are DERIVED from the stub's declared geometry
// constants below — not copied from a passing run — so the assertion
// has an independent basis.  If production changes a formula, at least
// one of these assertions will go RED.
//
// Sabotages that must all go RED:
//   (A) skip requestAnimationFrame(doLayout) in repositionAnnotation
//   (B) swap "left"/"right" side args in doLayout
//   (C) replace " Q " with " X " in the path setAttribute call
//   (D) replace midX with 99999 in drawConnectors
//   (E) remove the style.top writes from layoutMargin
// ====================================================================

// ---- geometry constants ----
// These match the values hard-wired in _DOM_STUB.
var MARK_TOP   = 100, MARK_H = 20, MARK_LEFT = 300, MARK_RIGHT = 500;
var FRAME_L    = 100, FRAME_T = 0;
var NOTE_H     = 30,  NOTE_CLAMP = Math.min(30, 22);  // min(height, 22) used in drawConnectors
var L_NOTE_R   = 90;          // noteEl.right when side = "left"
var R_NOTE_L   = 910;         // noteEl.left  when side = "right"
var BOW_R      = 8, BOW_L = -8;
var MARGIN_TOP = 0;           // both margins have getBoundingClientRect().top = 0

// layoutMargin: top = markTop - marginTop + markH/2 - noteH/2
var NOTE_TOP_EXP = MARK_TOP - MARGIN_TOP + MARK_H / 2 - NOTE_H / 2;
// = 100 - 0 + 10 - 15 = 95

// drawConnectors: fromY = noteRect.top - frameTop + NOTE_CLAMP/2
//   noteRect.top is style-driven: parseFloat(style.top)||0 = NOTE_TOP_EXP
var FROM_Y_EXP = NOTE_TOP_EXP - FRAME_T + NOTE_CLAMP / 2;
// = 95 - 0 + 11 = 106

// toY = markTop - frameTop + markH/2  (same for both sides)
var TO_Y_EXP = MARK_TOP - FRAME_T + MARK_H / 2;
// = 100 - 0 + 10 = 110

// Right-side:
var R_FROM_X = R_NOTE_L - FRAME_L;                        // 910 - 100 = 810
var R_TO_X   = MARK_RIGHT - FRAME_L;                      // 500 - 100 = 400
var R_MID_X  = (R_FROM_X + R_TO_X) / 2;                   // (810+400)/2 = 605
var R_MID_Y  = (FROM_Y_EXP + TO_Y_EXP) / 2 + BOW_R;      // (106+110)/2 + 8 = 116

// Left-side:
var L_FROM_X = L_NOTE_R - FRAME_L;                        // 90 - 100 = -10
var L_TO_X   = MARK_LEFT - FRAME_L;                       // 300 - 100 = 200
var L_MID_X  = (L_FROM_X + L_TO_X) / 2;                   // (-10+200)/2 = 95
var L_MID_Y  = (FROM_Y_EXP + TO_Y_EXP) / 2 + BOW_L;      // (106+110)/2 - 8 = 100

// PATH_RE validates the full "M fromX fromY Q midX midY toX toY" structure.
// If " Q " is mutated to " X " (or anything else), the regex fails to match
// and the structure assertion goes RED.  If any coordinate is wrong the
// per-value assertions go RED.
var PATH_RE = /^M\\s+([-\\d.]+)\\s+([-\\d.]+)\\s+Q\\s+([-\\d.]+)\\s+([-\\d.]+)\\s+([-\\d.]+)\\s+([-\\d.]+)$/;

function assertPath(d, label, expFromX, expFromY, expMidX, expMidY, expToX, expToY) {
  var m = d && d.match(PATH_RE);
  // !!m: false for null (no regex match), undefined (d was absent), falsy.
  // m !== null would be a false positive when d is undefined — don't use it.
  assert(label + ": M...Q... structure", !!m);
  if (!m) return;
  assert(label + ": fromX", Math.abs(parseFloat(m[1]) - expFromX) < 0.01);
  assert(label + ": fromY (layout-driven via style.top)", Math.abs(parseFloat(m[2]) - expFromY) < 0.01);
  assert(label + ": midX",  Math.abs(parseFloat(m[3]) - expMidX)  < 0.01);
  assert(label + ": midY",  Math.abs(parseFloat(m[4]) - expMidY)  < 0.01);
  assert(label + ": toX",   Math.abs(parseFloat(m[5]) - expToX)   < 0.01);
  assert(label + ": toY",   Math.abs(parseFloat(m[6]) - expToY)   < 0.01);
}

// ---- clean re-arm ----
connectorChildren.length = 0;
noteEl._removed      = false;
noteEl._movedToLeft  = false;
noteEl._movedToRight = false;
noteEl._side         = "left";
noteEl.style.top     = "";      // reset so style-driven rect starts at 0 before layoutMargin runs
noteEl.style.display = "";
markEl._replaced     = false;
DATA.pages[0].annotations = [
  { id: "a0", content: "Crush, do not cut.", position: "margin_left",
    type: "correction", matched: true },
];
DATA.totals = { annotations: 1, matched: 1 };
state.leftItems  = [{ ann: DATA.pages[0].annotations[0], el: noteEl }];
state.rightItems = [];
state.editingId  = null;

// Seed a stale left-side connector.
// If connectorLayer.innerHTML="" does NOT fire, this entry survives and
// connectorChildren.length > 1 after reposition — test goes RED (sabotage A).
var staleLeftConnector = {
  _isStale: true,
  dataset: { annId: "a0" },
  remove: function() {
    var idx = connectorChildren.indexOf(this);
    if (idx !== -1) connectorChildren.splice(idx, 1);
  },
};
connectorChildren.push(staleLeftConnector);
assert("geo setup: stale connector seeded",
  connectorChildren.length === 1 && connectorChildren[0]._isStale);

repositionAnnotation("a0");
// requestAnimationFrame(doLayout) fires synchronously:
//   (1) connectorLayer.innerHTML="" → connectorChildren.length = 0  (stale gone)
//   (2) layoutMargin(rightItems,"right") → sets noteEl.style.top = NOTE_TOP_EXP + "px"
//   (3) drawConnectors(anchored,"right") → creates path, appends to connectorChildren

assert("geo: stale connector cleared (innerHTML= fires after reposition-right)",
  connectorChildren.length === 1 && !connectorChildren[0]._isStale);
assert("geo: new connector is for a0",
  connectorChildren.length > 0 && connectorChildren[0].dataset.annId === "a0");

var d_right = connectorChildren[0]._attrs && connectorChildren[0]._attrs.d;
assert("geo: path d attribute exists after reposition-right", typeof d_right === "string");

assertPath(d_right, "geo right",
  R_FROM_X, FROM_Y_EXP, R_MID_X, R_MID_Y, R_TO_X, TO_Y_EXP);

// ---- toggle back to left: every coordinate must flip ----
var staleRightConnector = connectorChildren[0];
staleRightConnector._isStale = true;

repositionAnnotation("a0");
// doLayout clears (stale gone) and redraws for left side.

assert("geo: 1 connector after reposition back to left", connectorChildren.length === 1);
assert("geo: stale right connector cleared",
  connectorChildren.length > 0 && !connectorChildren[0]._isStale);

var d_left = connectorChildren[0]._attrs && connectorChildren[0]._attrs.d;
assert("geo: path d attribute exists after reposition-left", typeof d_left === "string");

assertPath(d_left, "geo left",
  L_FROM_X, FROM_Y_EXP, L_MID_X, L_MID_Y, L_TO_X, TO_Y_EXP);

// ====================================================================
// --- connector geometry: delete removes connector from layout ----
//
// deleteAnnotation directly removes the connector (conn.remove()) AND
// triggers doLayout, which clears and rebuilds from state.  After both
// steps the connector layer must be empty.
// ====================================================================

// Current state: a0 on left margin, connectorChildren = [left_path].
// Re-use that path as the tracked connector for the delete test.
var seededConnForDelete = connectorChildren[0];
seededConnForDelete._markedForDelete = true;
DATA.pages[0].annotations = [
  { id: "a0", content: "Crush.", position: "margin_left",
    type: "correction", matched: true },
];
DATA.totals = { annotations: 1, matched: 1 };
state.leftItems  = [{ ann: DATA.pages[0].annotations[0], el: noteEl }];
state.rightItems = [];
noteEl._removed = false;
markEl._replaced = false;

deleteAnnotation("a0");
// Steps that fire:
//   (1) a0 spliced from annotations
//   (2) els.connectorLayer.querySelector('[data-ann-id="a0"]') → seededConnForDelete
//       seededConnForDelete.remove() → spliced from connectorChildren
//   (3) requestAnimationFrame(doLayout):
//       connectorLayer.innerHTML="" → connectorChildren.length = 0 (idempotent)
//       layoutMargin([],…) both return early → no new connector appended

assert("delete-geo: seeded connector directly removed by deleteAnnotation",
  !connectorChildren.some(function(p) { return p._markedForDelete; }));
assert("delete-geo: no connector remains after doLayout",
  connectorChildren.length === 0);
assert("delete-geo: connectorLayer.querySelector returns null after delete",
  els.connectorLayer.querySelector('[data-ann-id="a0"]') === null);

console.log("Results:", PASS, "passed,", FAIL, "failed");
if (FAIL > 0) process.exit(1);
"""


class TestEditingHandlers:
    def test_all_handlers_execute_correctly(self, node: str, script: str) -> None:
        """Run edit / delete / reposition / export under a DOM stub.

        Exercises the REAL doLayout → layoutMargin → drawConnectors call chain
        and asserts on connector path geometry, not just that doLayout was called.
        """
        fn_cssEscape    = _extract_function(script, "cssEscape")
        fn_refreshActive = _extract_function(script, "refreshActive")
        fn_bindHover    = _extract_function(script, "bindHover")
        fn_applyFilters = _extract_function(script, "applyFilters")
        fn_drawConn     = _extract_function(script, "drawConnectors")
        fn_layoutMargin = _extract_function(script, "layoutMargin")
        fn_doLayout     = _extract_function(script, "doLayout")
        fn_delete       = _extract_function(script, "deleteAnnotation")
        fn_repos        = _extract_function(script, "repositionAnnotation")
        fn_edit         = _extract_function(script, "startEdit")

        assert fn_cssEscape,    "cssEscape not found in generated script"
        assert fn_refreshActive,"refreshActive not found in generated script"
        assert fn_bindHover,    "bindHover not found in generated script"
        assert fn_applyFilters, "applyFilters not found in generated script"
        assert fn_drawConn,     "drawConnectors not found in generated script"
        assert fn_layoutMargin, "layoutMargin not found in generated script"
        assert fn_doLayout,     "doLayout not found in generated script"
        assert fn_delete,       "deleteAnnotation not found in generated script"
        assert fn_repos,        "repositionAnnotation not found in generated script"
        assert fn_edit,         "startEdit not found in generated script"

        harness = (
            _DOM_STUB
            + "\n"
            + fn_cssEscape
            + "\n"
            + fn_refreshActive
            + "\n"
            + fn_bindHover
            + "\n"
            + fn_applyFilters
            + "\n"
            + fn_drawConn
            + "\n"
            + fn_layoutMargin
            + "\n"
            + fn_doLayout
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


# ---------------------------------------------------------------------------
# Template invariant: JS function bodies must be plan-independent
# ---------------------------------------------------------------------------


class TestTemplateInvariant:
    def test_function_bodies_identical_across_plans(self, node: str) -> None:
        """The Jinja template must not embed plan data inside function bodies.

        Render two plans with completely different content and verify that
        doLayout / layoutMargin / drawConnectors / applyFilters are byte-identical.
        If they differ the template has accidentally made the logic plan-specific.
        """
        plan_a = _plan()
        plan_b = AnnotationPlan(
            title="A Completely Different Book",
            prince_persona="Dumbledore",
            pages=[
                AnnotatedPage(
                    page_number=1,
                    original_text="Just one sentence.",
                    annotations=[],
                )
            ],
        )

        checked_fns = (
            "doLayout", "layoutMargin", "drawConnectors", "applyFilters"
        )

        def get_bodies(plan: AnnotationPlan) -> dict[str, str]:
            html_text, _ = _render(plan, None)
            matches = list(re.finditer(r"<script>(.*?)</script>", html_text, re.DOTALL))
            src = matches[-1].group(1)
            return {name: _extract_function(src, name) for name in checked_fns}

        bodies_a = get_bodies(plan_a)
        bodies_b = get_bodies(plan_b)

        for name in checked_fns:
            assert bodies_a[name] == bodies_b[name], (
                f"JS function '{name}' differs between plans — "
                "the template must not embed plan data inside function bodies."
            )
