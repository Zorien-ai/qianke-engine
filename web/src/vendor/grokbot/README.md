# GrokBot avatar engine vendor

Source: https://github.com/ArvinYin1/grokbot-animation-anatomy

Copied files:

- `grok-player.js` — browser ESM port of the Grok Bot avatar engine, zero dependencies.
- `grok-recipes.json` — animation data extracted from the Grok Bot macOS app.

## Usage boundary

The repository README says MIT, but there is no `LICENSE` file at the source repository.
The README also states that the animation data is extracted from the original app and
published for study only; the underlying design/data belong to their original owners.

This copy is used as a **local prototype / evaluation** for the C-end interactive avatar.
Before commercial launch, replace the extracted recipes with our own character shapes and
animation data, or obtain explicit permission from the rights holder. Do not redistribute
this vendor folder as a standalone asset pack.
