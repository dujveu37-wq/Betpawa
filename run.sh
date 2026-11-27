#!/usr/bin/env bash
# Runs the collector for ~5h40 and commits the data every 20 min.
git config --global user.name "collector"
git config --global user.email "collector@users.noreply.github.com"
git rebase --abort 2>/dev/null
git symbolic-ref -q HEAD >/dev/null || git checkout -q -B "${GITHUB_REF_NAME:-main}"
commit() {
  git add data state.txt 2>/dev/null
  git diff --cached --quiet && return
  git commit -qm "data $(date -u +%F\ %H:%M)"
  for i in 1 2 3; do
    git pull -q --rebase --autostash && git push -q && return
    echo "push echoue (essai $i), nouvel essai"
    git rebase --abort 2>/dev/null
    sleep 5
  done
  echo "ECHEC: donnees non poussees"
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
