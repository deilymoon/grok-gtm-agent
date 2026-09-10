# Grok GTM Agent — Product Video Showcase

Fullscreen light product-video demo for screen recording and social capture. It is a separate visualization layer and does not change the core GTM agent.

## Run

```bash
cd video_demo
python3 -m http.server 8765
# open http://127.0.0.1:8765/
```

Without query parameters the demo autoplays in an ~18 second loop.

Frozen scenes for screenshots:

- `?scene=intro`
- `?scene=icp`
- `?scene=discovery`
- `?scene=signals`
- `?scene=scoring`
- `?scene=top5`
- `?scene=deepdive`
- `?scene=end`

The source data in `data/hero.json` is a compact, sanitized representation of the real LIVE hero run used for the showcase: 15 companies researched, 55 verified signals, and 5 final opportunities.

The rendered MP4 used for the launch post is intentionally not required to run this demo; the HTML/CSS/JS source is reproducible locally.
