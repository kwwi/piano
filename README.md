# piano

An interactive, web-based piano you can play with your mouse, touch, or computer
keyboard. Notes are synthesized in real time with the Web Audio API — no audio
files required.

## Features

- Three-octave keyboard (C3–C5) with realistic white/black key layout
- Real-time tone synthesis using the Web Audio API (attack/decay/release envelope)
- Play with mouse/touch or your computer keyboard
  - Lower octave: `Z S X D C V G B H N J M`
  - Upper octave: `Q 2 W 3 E R 5 T 6 Y 7 U I`
- Polyphony (play chords), on-screen key labels, and a labels toggle

## Tech stack

- [React](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/)
- [Vite](https://vite.dev/) for the dev server and build
- Web Audio API for sound synthesis

## Getting started

Requires [Node.js](https://nodejs.org/) 20+ (developed on Node 22).

```bash
npm ci        # install dependencies (use `npm install` if there is no lockfile yet)
npm run dev   # start the dev server at http://localhost:5173
```

## Available scripts

| Script              | Description                                  |
| ------------------- | -------------------------------------------- |
| `npm run dev`       | Start the Vite dev server (port 5173)        |
| `npm run build`     | Type-check and build for production          |
| `npm run preview`   | Preview the production build (port 4173)      |
| `npm run lint`      | Run ESLint                                    |
| `npm run typecheck` | Type-check without emitting output           |

## Cloud Agent environment

This repository includes a [`.cursor/environment.json`](.cursor/environment.json)
so Cursor Cloud Agents install dependencies with `npm install` and run the dev
server automatically on port 5173.
