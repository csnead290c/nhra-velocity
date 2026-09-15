# Practical Identifiability — v0.29

## Why this exists

A nonlinear optimizer can return a precise-looking best-fit value even when the available Runs do not truly constrain that parameter. Local covariance/correlation is useful, but it is only a local linear approximation around the optimum.

v0.29 adds **profile-objective scans** for shared vehicle parameters in a Joint Reconstruction Study.

## Method

For a selected shared parameter:

1. start from the completed joint fit;
2. force that parameter to a sequence of nearby values within its engineering bounds;
3. warm-start all other shared and Run-specific nuisance parameters from the joint optimum;
4. re-optimize every other allowed parameter at each forced value;
5. record the robust objective after re-optimization;
6. report the objective increase relative to the unconstrained optimum.

This asks the practical question: **if this parameter were different, could the other allowed parameters compensate without materially worsening the measured-vs-model fit?**

## Interpretation

- a steep profile means the supplied Runs strongly resist moving the parameter;
- a broad/flat profile means the parameter remains weakly identified after the other freedom is re-optimized;
- a one-sided profile means the evidence constrains one direction more strongly than the other;
- a profile minimum that shifts away from the original optimum indicates numerical instability or an insufficient scan/optimization budget and should be investigated.

The default practical threshold is Δobjective = 3.84 because it is a familiar one-parameter chi-square reference. **It is not presented as an exact 95% posterior/confidence interval.** The inverse solver uses normalized engineering residuals with robust `soft_l1` loss, so the scan is a practical-identifiability diagnostic unless stronger probabilistic assumptions are separately justified.

## Persistence

`.nhrafit` format v3 stores completed profile scans under the study package. Older v1/v2 packages remain readable. Each profile stores:

- parameter and fitted optimum;
- engineering lower/upper bounds;
- scan values;
- robust objective and Δobjective;
- success/message at each re-optimization point;
- practical interval inside the selected threshold;
- status (`bounded_in_scan`, `one_sided_in_scan`, or `flat_in_scan`);
- interpretation note.

## Relationship to future uncertainty work

Profile objective is deliberately the next layer after local covariance, not the final uncertainty system. Future work can add:

- wider/adaptive profiles;
- two-parameter contour scans for highly correlated terms;
- bootstrap/Monte Carlo sensitivity to measurement noise and Run selection;
- Bayesian posterior sampling where priors and likelihood assumptions are justified;
- leave-one-Run-out influence analysis.
