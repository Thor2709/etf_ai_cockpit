# ISSUE-0035 browser gate

Source app readiness on `http://127.0.0.1:8595/` returned HTTP 200 and the
route `/data-health` rendered in the in-app browser. Packaged-native readiness
on `http://127.0.0.1:8565/` also returned HTTP 200 and `/data-health` rendered
with the same dark shell and inventory content.

Visual evidence is preserved in `ISSUE-0035-desktop.png`,
`ISSUE-0035-mobile.png` and `ISSUE-0035-packaged.png`. Source and packaged
console logs contained only `Flutter app loaded`; no browser error was seen.
The semantic snapshot exposed only Flet's accessibility-toggle control, so a
full keyboard/focus assertion is not claimed. The browser surface is otherwise
verified; closure remains pending the missing semantic and full-suite gates.
