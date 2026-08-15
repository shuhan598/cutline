# Ignore Multi-Value Buffer Binding Design

## Goal

Temporarily ignore a complete `buffer_realtime` record when its
`bound_source_name` contains multiple comma-separated non-empty values.
The ignored record must not produce validation, aggregation, or pipeline
errors.

## Scope

- Treat an input as multi-value only when splitting on the ASCII comma `,`
  produces at least two non-empty trimmed values.
- Ignore the complete matching `buffer_realtime` record.
- Do not include its quantity in order inventory or physical main inventory.
- Do not use it to create main/order aggregation state, warnings, candidates,
  or cutline decisions.
- Preserve all existing behavior for normal single values, blank values, and
  other invalid values.
- Do not parse the values or introduce new product/order mapping rules.

## Implementation

Create one shared predicate for detecting the temporary multi-value format.
Use it consistently in backend completeness validation, snapshot inventory
conversion, and `MainBufferAggregator` so both API execution and direct core
usage have the same behavior.

## Verification

Add regression coverage proving that:

1. A comma-separated record is silently ignored.
2. Its inventory is not counted.
3. It does not create an aggregation issue.
4. Normal single-value records continue to use the existing mapping rules.

Run the focused adapter and aggregation tests, followed by the complete test
suite, Pyright, and `compileall`.

## Git Constraints

Do not run `git add`, `git commit`, or `git push`.
