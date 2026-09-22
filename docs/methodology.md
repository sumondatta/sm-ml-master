# Methodology

Why the code is arranged the way it is, and what each choice costs. Read this
before changing the evaluation protocol or the target column — both have
non-obvious failure modes that produce better-looking numbers and worse science.

---

## 1. What the model is for, and why that decides everything else

The goal is to estimate soil moisture **where no sensor is installed**. That one
sentence rules out a large fraction of what a soil moisture ML paper normally
does:

- **No lagged target.** Yesterday's reading is by far the strongest predictor of
  today's, and using it requires a probe in the ground. It is offered as an
  explicit opt-in (`add_autoregressive_features`) for the gap-filling and
  short-horizon-forecast cases it is legitimately for, and is absent from the
  default feature set.
- **No site statistics.** A site's mean, minimum or observed range is unavailable
  at a new field, and including any of them inflates a leave-site-out score
  while adding nothing deployable.
- **Gridded soil properties are preferred over measured ones.** A new field has
  SoilGrids, not a laboratory particle-size analysis. `build_static_features`
  substitutes the `*_grid` columns by default. Training on field-measured
  texture overstates what the model can do in the setting it is meant for.

Each of these makes the reported numbers worse. That is the intended direction.

## 2. Splits

Soil moisture is autocorrelated in time (today resembles yesterday) and in space
(two stations in one field see one storm). A random k-fold therefore places
near-duplicate rows on both sides of the boundary and scores memorization.

| split | question it answers |
|---|---|
| `leave_site_out` | Can it predict at a field with no sensor? **The primary one.** |
| `spatial_block` | Same, but holding out whole regions, so a held-out site cannot borrow from a neighbour. |
| `leave_year_out` | Can it predict an unseen year — a drought, an unusual season? |
| `forward_chaining` | Can it predict the future from the past? The operational case. |
| `leave_site_and_year_out` | Both at once. The strictest, and the closest to deployment. |
| `random_kfold_DO_NOT_USE` | Included only to measure how much it flatters the model. |

`forward_chaining` takes a `gap_days`. Set it to at least the longest rolling
feature window (365 by default), or test rows immediately after the cut share
most of their feature window with training rows.

Verify any new split with `describe_splits`: `sites_shared` must be zero for a
site-holdout scheme.

## 3. Metrics

`ubRMSE` — RMSE after removing the mean difference — is the headline in the soil
moisture validation literature because much of the disagreement between any two
soil moisture estimates is a constant offset from sensor calibration and from the
mismatch between a point measurement and a modelled volume. That offset is real
but it is a different problem from getting the dynamics right, and `RMSE² =
ubRMSE² + bias²` separates them cleanly.

`KGE` decomposes into correlation, bias ratio and variability ratio, which is the
diagnosis wanted: a soil moisture model typically fails in one of those three
ways and the remedy differs for each.

`anomaly_correlation` removes the seasonal climatology from both series before
correlating. A model can score a high raw correlation by reproducing the annual
cycle alone — on a synthetic check, a purely seasonal predictor scored r = 0.89
raw and 0.03 anomaly.

### The decomposition that matters most

Between-site variance is **84 %** of the total in the reference corpus: texture
alone sets a field's mean water content across a range far wider than any one
field varies over a season. So a pooled correlation is mostly a measure of
whether the model can rank fields.

`skill_decomposition` reports:

- `r_between` — correlation of per-site means. Can it tell a wet field from a dry
  one?
- `r_within` — median within-site temporal correlation. Can it tell when *this*
  field needs water?

A static prediction of field capacity from texture scored a pooled **r = 0.90**
and an `r_within` of **exactly 0**. Quote both or neither.

## 4. The target column

A dielectric probe cannot see water held on clay surfaces — bound water has a
permittivity near that of ice rather than of free water — so it reads low, and
increasingly so as clay rises. `smml.physics.dielectric.clay_bias` estimates the
shortfall from a four-phase mixing model.

Training on the raw reading teaches the model to reproduce the bias. Measured on
the reference corpus under leave-site-out, scored against true water content:

| trained on | RMSE | bias | r_within |
|---|---|---|---|
| `theta_obs_m3m3` | 0.0692 | −0.0422 | 0.790 |
| `theta_clay_corrected_m3m3` | **0.0486** | **−0.0057** | 0.788 |

Correcting removes the bias and cuts RMSE by 30 % while leaving temporal skill
unchanged — which is the expected signature, since the correction is a
texture-dependent offset and not a change in dynamics.

`resolve_target` makes the choice explicit at every pipeline stage. It exists
because the first implementation computed the corrected column and then fitted on
the raw one, leaving the bias in place with no visible sign that anything was
wrong.

**The correction is never applied in place.** The original observation stays in
`theta_m3m3`; corrections go to their own columns. A correction computed from an
*estimated* clay content can be worse than none, and the only way to find out is
to be able to compare.

## 5. Uncertainty as sample weight

The corpus mixes gravimetric samples accurate to 0.01 m³/m³ with values digitized
off a small printed figure. `METHOD_UNCERTAINTY` assigns a baseline per method,
QC inflates it where a check fired, and `uncertainty_weights` turns it into
inverse-variance sample weights clipped to [0.2, 5]. The clipping stops one very
precise observation from dominating a fold and stops a very uncertain one from
being effectively discarded.

## 6. Hyperparameter search

The inner folds are **site-disjoint**, like the outer evaluation. Tuning against a
random split and reporting a leave-site-out score selects hyperparameters that
exploit leakage.

Early stopping uses a validation slice split **by site**, not at random, so it
cannot leak either.

`nested_cv` runs an independent search inside every outer fold. It is the only
way to get an estimate not biased by hyperparameter selection, and it costs
`n_outer` complete searches. Normal practice: a single search during development,
one nested run for a number that gets published.

Studies persist to SQLite, so a search can be interrupted, inspected mid-flight
and extended later by calling again with the same `study_name`.

## 7. Physics as inductive bias, not decoration

- **Monotone constraints.** Water content cannot fall when antecedent
  precipitation rises, all else equal. `build_monotone_constraints` signs every
  feature whose direction is known. This costs a little training fit and buys
  extrapolation that stays physical outside the training range — which is the
  whole point for a model meant for new fields.
- **A water-balance bucket as a feature.** `simple_bucket_state` runs a one-layer
  balance alongside the data. Giving a tree a physically integrated state
  variable lets it represent memory no fixed set of rolling windows can, and the
  same bucket is the baseline the learned model has to beat.
- **Entity-aware LSTM.** The static input gate is computed once per site from
  soil attributes and held fixed in time, so those attributes can only modulate
  *how forcings are used* — they cannot act as a site-identifying lookup key,
  which is exactly what a plain LSTM given them as extra channels will do.

## 8. Baselines that must be beaten

`global_mean`, `depth_climatology`, `field_capacity`, `bucket`, and
`persistence`. Reporting a neural network's RMSE without these says nothing: soil
moisture has a strong seasonal cycle and enormous day-to-day persistence, so a
model can look accurate while adding no information.

`persistence` is **not** a valid baseline for the primary task — it needs a
sensor. It is included because it is correct for gap-filling, and because its
score shows how much of a good-looking result is autocorrelation.

## 9. Reading results from synthetic data

The synthetic corpus is generated by a tipping-bucket model parameterized with
Saxton-Rawls pedotransfer functions. A Saxton-Rawls baseline is therefore
unusually strong on it — the baseline and the generator share an assumption.

Treat cross-model comparisons on synthetic data as a test of the machinery, not
as evidence about real soils. What synthetic data *is* good for: verifying
conservation, checking that a split does not leak, confirming that a correction
moves predictions the right way, and measuring detector recall against faults
whose location is known exactly.
