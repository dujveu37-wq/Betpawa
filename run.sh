#!/usr/bin/env bash
# Runs the collector for ~5h40 and commits the data every 20 min.
commit() {
  git add data state.txt 2>/dev/null
  git diff --cached --quiet && return
  git -c user.name="collector" -c user.email="collector@users.noreply.github.com" commit -qm "data $(date -u +%F\ %H:%M)"
  git pull -q --rebase && git push -q
}
python collect.py "$@" --max-minutes 340 &
PID=$!
while kill -0 $PID 2>/dev/null; do
  for i in $(seq 1 20); do kill -0 $PID 2>/dev/null || break; sleep 60; done
  commit
done
wait $PID; CODE=$?
commit
exit $CODE
