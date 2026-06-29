#!/usr/bin/env bash
set -euo pipefail

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

test -f "${skill_dir}/SKILL.md"
test -f "${skill_dir}/bootstrap.sh"

grep -q '^name: cyclaw-optimize$' "${skill_dir}/SKILL.md"
grep -q '^description:' "${skill_dir}/SKILL.md"
bash -n "${skill_dir}/bootstrap.sh"
