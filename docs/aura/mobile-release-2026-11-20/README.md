# Aura mobile composer — visual evidence (20 Nov 2026)

Headless Chromium with phone emulation, real local webapp and gateway, fake model only.
**Not a physical Android device.** Before = production base `f8fda1d3`; after = PR #34.

| Width | Collapsed composer before → after | Starters visible above composer | Mic buttons |
|---|---|---|---|
| 320 | 188 → 100 px | 2/4 → 4/4 (horizontal row) | 2 → 1 |
| 360 | 188 → 100 px | 2/4 → 4/4 | 2 → 1 |
| 390 | 188 → 100 px | 3/4 → 4/4 | 2 → 1 |
| 430 | 188 → 100 px | 4/4 → 4/4 | 2 → 1 |
| 768 / 1440 | 152 → 104 px | composer centred above starters | 2 (desktop keeps dictation) |

No horizontal overflow at any width, light or dark. During a live call, a voice alert or an
open On-device panel, the mode row returns to its own line (`active-*.png`).
