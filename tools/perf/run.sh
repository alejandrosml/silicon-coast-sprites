#!/bin/bash
# run.sh - launch BG:EE or BG2:EE on macOS with the scfps frame logger (MIT).
# usage: run.sh <path to the game's .app> [log.csv]
set -e
APP="${1:?usage: run.sh <game .app> [log.csv]}"
LOG="${2:-$PWD/scfps-$(date +%Y%m%d-%H%M%S).csv}"
case "$LOG" in /*) ;; *) LOG="$PWD/$LOG" ;; esac
HERE="$(cd "$(dirname "$0")" && pwd)"
EXE="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist")"
[ -f "$HERE/scfps.dylib" ] || { echo "build scfps.dylib first (see README.md)"; exit 1; }
echo "log: $LOG"
SCFPS_LOG="$LOG" DYLD_INSERT_LIBRARIES="$HERE/scfps.dylib" "$APP/Contents/MacOS/$EXE"
