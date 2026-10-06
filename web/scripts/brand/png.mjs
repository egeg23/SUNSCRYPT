// SVG → PNG заданного размера через Chromium (Playwright).
// node png.mjs <in.svg> <out.png> <size>
import { readFileSync } from 'node:fs';
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
const [,, svg, out, size] = process.argv;
const markup = readFileSync(svg, 'utf8').replace('<svg ', `<svg style="width:${size}px;height:${size}px;display:block" `);
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: +size, height: +size } });
await p.setContent(`<html><body style="margin:0">${markup}</body></html>`);
await p.screenshot({ path: out, omitBackground: true });
await b.close();
