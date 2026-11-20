# Aura composer and conversation mode — after the references (20 Nov 2026)

`reference-*.jpg` are the targets Melvin supplied; Aura's existing violet palette is used instead
of their blue and green. Screens are headless Chromium, fake model and fake speech; **not a
physical Android device.**

**Composer:** text on top, one toolbar below at every width — `+` and a model chip on the left,
On-device, Voice (round violet on phones) and Send on the right; a soft violet glow in dark.
The chip shows the model that answers (`GET /api/aura/provider`) and opens Settings → Model;
there is no in-composer model switching, multi-model, web search or temporary chat, because
Aura has none of those.

**Conversation mode:** full-screen on phones, a card over a dim backdrop on wide screens:
brand header, state headline, a violet orb that turns faster while hearing or speaking (static
with reduced motion), the live transcript as a fading caption, and a round control bar
(mute · end · stop speaking). Fixes a pre-existing bug: the composer dock's `translate`
trapped the "full-screen" call view inside the composer.
