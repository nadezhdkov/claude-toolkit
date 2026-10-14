- Benchmark case `relay-resume`: a feature left half done by an earlier session (a handoff file with
  decisions that are not in the code, one uncommitted edit), resumed in a fresh session with
  "continue from where the last session stopped". The case sets `CTK_RELAY=1`, so the with arm gets the
  state from the `continuity` hook and the without arm has to find it. Three deterministic checks
  (the feature works, the decisions hold, the earlier work is intact); `tests/test_benchmark_relay.py`
  proves them without Claude. The runner now honours a case's `env` key, as `claude plugin eval` does.
