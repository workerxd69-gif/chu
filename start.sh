#!/bin/bash
set -e
cd "$(dirname "$0")"
mkdir -p data
exec python3 bot.py
