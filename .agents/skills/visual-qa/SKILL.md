---
name: visual-qa
description: Check a UI change by looking at deterministic screenshots (ctk shoot) against a defect checklist and baselines. Use before calling visible work done.
---

# Visual QA

Never claim a UI change works from reading the code. Capture it, look at the
images, and fix what you see.

## 1. Capture

Pick the backend and capture every state the change affects:

- Web: start the dev server if needed, then
  `ctk shoot web <url|file> --size 1280x720` and `--size 390x844` (mobile);
  add `--dark` when the app supports dark mode, `--full-page` for long pages,
  `--wait-for <selector>` for content loaded later, `--mask-selector` for
  clocks, avatars and other changing content.
- Godot: `ctk shoot godot <project> --scene res://… --frames <n>` (use enough
  frames for animations to settle).
- Desktop apps: `ctk shoot desktop --size WxH --delay <s> -- <command>`.

Include the states that usually break: empty, loading, error, long text,
many items, narrow width, hover/focus if reachable through the URL or scene.

Combine the captures into one image with `ctk shoot sheet <pngs…>` and read
it; open single captures only when a detail needs a closer look. Treat any
`note:` line (HTTP errors, console or page errors, Godot script errors) as a
bug to investigate.

## 2. Check

Go through the list and write down each defect with the capture number and
position:

- Layout: overflow, horizontal scrollbars, overlapping or cut-off elements,
  broken alignment and spacing, elements off-screen at small sizes.
- Text: truncation, wrapping in odd places, missing translations or
  placeholder text, wrong font, unreadable sizes.
- Colour: contrast too low (body text below 4.5:1), dark-mode leftovers
  (white boxes, invisible icons), states that look disabled by mistake.
- Images and icons: missing, stretched, blurry, wrong aspect ratio.
- Consistency with the rest of the app (spacing scale, components, tone).
- Godot: UI anchored wrongly at other resolutions, z-order, pixel snapping.

## 3. Compare with baselines

If the project keeps baselines (look for `--baseline` paths in docs, tests or
a `shots/` directory), capture with `--baseline <path>`. A difference exits 1
with the percentage, a bounding box and a diff image: confirm the changed
area is exactly what the task intended. Update a baseline with `--update`
only when the change is intended, and say so in the PR.

## 4. Fix and recapture

Fix each defect, capture again with the same options, and compare the
before/after pair in a contact sheet. Repeat until the list is empty.

## Report

List the captures (paths), the defects found and fixed, anything left with the
reason, and the baseline results. Attach or link the final contact sheet
when the change goes into a PR.
