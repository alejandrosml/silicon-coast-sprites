#!/usr/bin/env python3
"""summary.py - Silicon Coast: summarise one or more scfps logs (MIT).

usage: summary.py log.csv [log2.csv ...]

Uses the seconds between the "# mark ... scene-debut" and "# mark ... scene-fin" lines when they exist, otherwise
every second after the first five.
"""
import statistics
import sys

COLS = ['t_s', 'images', 'intervalle_moy_ms', 'intervalle_max_ms', 'cpu_rendu_moy_ms', 'cpu_rendu_max_ms',
        'attente_flush_moy_ms', 'cpu_processus_pct', 'memoire_mo', 'textures_envois', 'textures_mo',
        'dessins_par_image', 'visible', 'actif']


def load(path):
    rows, window, on, marked = [], [], False, False
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.startswith('# mark'):
                if 'scene-debut' in line:
                    on, marked, window = True, True, []
                elif 'scene-fin' in line:
                    on = False
                continue
            if line.startswith('#') or line.startswith('t_s'):
                continue
            values = [float(x) for x in line.strip().split(',')]
            if len(values) != len(COLS):
                continue
            row = dict(zip(COLS, values))
            rows.append(row)
            if on:
                window.append(row)
    return window if marked else [r for r in rows if r['t_s'] > 5]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for path in sys.argv[1:]:
        rows = load(path)
        if not rows:
            print(f'{path}: no data')
            continue
        med = lambda c: statistics.median(r[c] for r in rows)
        print(f'{path}: {len(rows)} s')
        print(f'  frames per second (median)      {med("images"):.0f}')
        print(f'  slowest frame (ms)              {max(r["intervalle_max_ms"] for r in rows):.0f}')
        print(f'  main-thread work per frame (ms) {med("cpu_rendu_moy_ms"):.1f}')
        print(f'  CPU (% of one core)             {med("cpu_processus_pct"):.0f}')
        print(f'  memory at the end (MB)          {rows[-1]["memoire_mo"]:.0f}')
        print(f'  texture uploads (MB/s)          {med("textures_mo"):.0f}')
        print(f'  draw calls per frame            {med("dessins_par_image"):.0f}')


if __name__ == '__main__':
    main()
