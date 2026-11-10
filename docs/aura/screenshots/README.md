# Aura screenshot evidence

Synthetic data only. Real local Webapp + FakeLLMServer; no real-model output.

Phone screenshots are 390 × 844 except the keyboard emulation (390 × 500).
Keyboard images emulate a reduced visual viewport; they do not show a real mobile IME.
Approval screenshots contain only a disposable local test-directory command.

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
| progress | [Light](progress-light.png) | [Dark](progress-dark.png) |
| approval | [Light](approval-light.png) | [Dark](approval-dark.png) |
| resume | [Light](resume-light.png) | [Dark](resume-dark.png) |

Additional evidence: [image + URL attachments](attachments-light.png),
[desktop rail](desktop-light.png), [streaming](streaming-dark.png).

Goal, source, approval and resume cards are captured from live UI elements.
Progress screenshots show the live card in its conversation context.

Generation: `python scripts/reveta/aura_browser.py` after the Webapp build.
The PR records the exact tested commit and command exit codes.
