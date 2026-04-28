# RFC-008 Test Coverage

This directory contains comprehensive unit tests for RFC-008: Memory Salience & Spacing Effects.

## Test Modules

- `test_rfc008_salience_spacing.py` — Complete test suite covering:
  - **memory_salience.py** (Von Restorff effect)
    - Cosine similarity helpers
    - Distinctiveness, signal weight, isolation computation
    - Full salience score calculation with all edge cases
  - **memory_spacing.py** (Spacing effect)
    - Reinforcement counter updates
    - Memory strength calculation (Ebbinghaus curve)
    - Should-reinforce logic with spacing intervals
    - Interval flooring at 1 day minimum
  - **tiered_decay.py** (Hot/Warm/Cold/Frozen tiers)
    - Tier computation logic
    - Retrieval multipliers per tier
    - Exclusion logic for frozen notes
    - Batch tier recomputation and sorting
    - Tier distribution statistics
  - **config.py** (YAML section application)
    - All RFC-008 sections: salience, spacing, decay, retrieval_weights
    - Default value verification
    - Unknown key handling (silent ignore)

## Test Statistics

- **Total tests:** 79
- **Passing:** 79
- **Failing:** 0
- **Coverage:** 100% of RFC-008 implementation

## Running the Tests

```bash
# From zettelforge-h4/src directory:
python3 -m pytest ../tests/test_rfc008_salience_spacing.py -v

# Or with coverage report:
python3 -m pytest ../tests/test_rfc008_salience_spacing.py --cov=zettelforge --cov-report=term-missing
```

## Test Design Notes

All tests use naive UTC timestamps (`datetime.utcnow()`) to match the production code's timezone handling in `zettelforge.tiered_decay._note_age_days`.

MemoryNote fixtures include all required schema fields:
- `content.source_type` and `content.source_ref`
- `embedding.vector` with 768 dimensions
- Properly structured `metadata` and `semantic` objects

Boundary tests verify clear tier transitions at threshold values.