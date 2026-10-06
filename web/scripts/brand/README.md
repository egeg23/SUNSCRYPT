# Генерация файлов бренда

Логотип, знак, надпись, favicon и аватар Telegram собираются скриптами отсюда.
Надпись — шрифт Unbounded SemiBold (600), переведённый в кривые.

```bash
python -m venv /tmp/fv && /tmp/fv/bin/pip install fonttools brotli
F=node_modules/@fontsource-variable/unbounded/files/unbounded-latin-wght-normal.woff2
/tmp/fv/bin/python scripts/brand/wordmark.py $F SUNSCRYPT 600 0.08 > /tmp/wm.txt
/tmp/fv/bin/python scripts/brand/build_brand.py . /tmp/wm.txt      # SVG
node scripts/brand/png.mjs $PWD/public/brand/avatar.svg $PWD/public/brand/telegram-avatar-640.png 640
node scripts/brand/png.mjs $PWD/src/app/icon.svg $PWD/src/app/apple-icon.png 180
```

`png.mjs` рендерит через Chromium из Playwright (путь к пакету — в импорте).
