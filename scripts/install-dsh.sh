#!/usr/bin/env bash
set -eu
prefix="${HOME}/.local/share/panelize-local/dsh"
node -e 'const [a,b]=process.versions.node.split(".").map(Number);if(a<24||(a===24&&b<9)){console.error("需要 Node.js >= 24.9");process.exit(1)}'
npm install --prefix "$prefix" --no-audit --no-fund @deepseek-ai/dsh@0.2.2-rc.5
"$prefix/node_modules/.bin/dsh" --version
