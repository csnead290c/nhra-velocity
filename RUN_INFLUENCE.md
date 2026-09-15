# Run Influence — v0.30

## Purpose

Joint reconstruction can look stable while depending heavily on one particular pass. v0.30 adds a leave-one-Run-out influence analysis to measure that dataset dependence directly.

For each measured Run in a Joint Reconstruction Study:

1. omit that Run;
2. retain the remaining Runs with their original evidence policies and nuisance allowlists;
3. remap retained Run-specific nuisance starts/overrides to their new internal Run indices;
4. warm-start shared parameters from the full-data optimum;
5. rerun the nonlinear joint fit;
6. compare every shared vehicle estimate against the full-data result.

## Reported influence

Each omitted Run reports:

- refit success/message;
- shared-parameter estimate without that Run;
- signed and absolute parameter shift;
- shift as a fraction of the parameter's engineering bound span;
- shift relative to the full-fit local standard error where meaningful;
- dominant affected parameter;
- overall influence classification.

Current classification uses maximum engineering-bound-span shift:

- `< 2%` — `low_influence`;
- `2–5%` — `moderate_influence`;
- `>= 5%` — `high_influence`.

This is an engineering stability diagnostic, not a probability statement and not a substitute for holdout predictive validation.

## Relationship to profile objective

The two diagnostics answer different questions:

- **profile objective**: can other parameters compensate if a selected parameter is forced away from its optimum?
- **Run influence**: how much does the fitted shared vehicle change if one pass is removed from the evidence set?

A parameter can have a steep profile but still be dominated by one Run, or have low individual Run influence but remain broadly confounded with another parameter. Both views are needed.

## Persistence

`.nhrafit` format v4 stores `run_influence` alongside residual decomposition, parameter diagnostics and profile scans. v1–v3 packages remain readable.
