# Aura screenshot evidence

Synthetic data only. Real local Webapp + FakeLLMServer; no real-model output.

Phone screenshots are 390 × 844 except the keyboard emulation (390 × 500).
Keyboard images emulate a reduced visual viewport; they do not show a real mobile IME.
Current approval screenshots use a loopback-only simulated action through the
existing pipe-to-shell guard, with a constant harmless response. It is not an
external send or every-tool approval proof. Step images show actual runtime
results under FakeLLMServer, including the declined and approved attempts.

| State | Light | Dark |
|---|---|---|
| empty | [Light](empty-light.png) | [Dark](empty-dark.png) |
| conversation | [Light](conversation-light.png) | [Dark](conversation-dark.png) |
| keyboard | [Light](keyboard-light.png) | [Dark](keyboard-dark.png) |
| navigation | [Light](navigation-light.png) | [Dark](navigation-dark.png) |
| settings | [Light](settings-light.png) | [Dark](settings-dark.png) |
| no-model | [Light](no-model-light.png) | [Dark](no-model-dark.png) |
| goal | [Light](goal-light.png) | [Dark](goal-dark.png) |
| source | [Light](source-light.png) | [Dark](source-dark.png) |
| progress (historical checkpoint; superseded by steps) | [Light](progress-light.png) | [Dark](progress-dark.png) |
| event-backed steps (390 × 844) | [Light](steps-light.png) | [Dark](steps-dark.png) |
| approval | [Light](approval-light.png) | [Dark](approval-dark.png) |
| resume | [Light](resume-light.png) | [Dark](resume-dark.png) |

Additional evidence: [image + URL attachments](attachments-light.png),
[desktop rail](desktop-light.png), [streaming](streaming-dark.png).

Goal, source, approval and resume cards are captured from local UI elements.
The original progress images predate the event-backed slice. Steps and approval
images were refreshed for implementation `9b929bfe`; other original images remain
historical evidence from the previous checkpoint. The steps area scrolls within
the existing context region; these phone views show the rows after scrolling.

Generation: `python scripts/reveta/aura_browser.py` after the Webapp build.
The PR records the exact tested commit and command exit codes.
