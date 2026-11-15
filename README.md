# Aura Zero

**Aura is Reveta's voice-first AI operator.** You talk or type a rough idea; Aura works out what you mean, asks one short question when it has to, and then does the work with tools, stopping for your approval before anything consequential. It is built for founders, business owners and creative people who want ideas turned into working products and operations without needing to be technical.

- Live preview: <https://aura-zero.onrender.com> (sign-in required)
- Current status, what is live and what is only in a pull request: [`docs/aura/CHECKPOINT.md`](docs/aura/CHECKPOINT.md)
- Attribution and licences: [`docs/aura/ATTRIBUTION.md`](docs/aura/ATTRIBUTION.md)

## What Aura is made of

- **Conversation first.** Each message is read as thinking aloud, unclear, a clear request, or something that needs approval. Goals are saved only when you confirm them.
- **Voice.** Spoken turns go through the same conversation, tools and approvals as typed chat, and replies are spoken back.
- **Tools with approvals.** Aura runs on the Hermes agent runtime. Tools that act for you wait for an approval tied to that exact action; spending caps and secret protection apply throughout.
- **Your own model keys.** Choose a provider and set daily spending limits in Settings, in the app rather than in server configuration.

What is actually live changes quickly. Treat `docs/aura/CHECKPOINT.md` as the source of truth: it separates built, tested, merged, deployed and checked-on-a-phone.

## Branches

- `aura/working-product-20261111` is the canonical product line. The live preview deploys from it, and new work targets it through pull requests.
- `main` is the untouched upstream baseline Aura was forked from. It is kept so upstream runtime fixes can be compared and brought in.
- Old branch tips are recorded in [`docs/aura/BRANCHES.md`](docs/aura/BRANCHES.md) so any retired work can be recovered.

## Running it

Aura ships as the Docker image built from this repository's `Dockerfile`; the Render start command configures it with `scripts/reveta/aura_config.py`. Everything beneath Aura's own screens (the agent loop, tools, gateway and command line, which is still called `hermes`) is the Hermes runtime, so its upstream documentation applies: <https://hermes-agent.nousresearch.com/docs/>.

## Built on Hermes Agent

Aura Zero is a fork of [Hermes Agent](https://github.com/NousResearch/hermes-agent) by [Nous Research](https://nousresearch.com), used under the MIT licence. The original `LICENSE` and its notices are kept unchanged. Files under `website/`, `skills/` and `optional-skills/` are the upstream runtime documentation and skills, and still describe Hermes Agent by name.

## Licence

MIT. See [`LICENSE`](LICENSE).
