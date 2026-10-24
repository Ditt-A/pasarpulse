# PasarPulse model archive

This directory contains the parent A100 run artifacts that are not part of the
compact reporting tables in `results/`:

- `proposed_gpu_v2/`, `proposed_gpu_run/`: GPU expert OOF predictions,
  postprocessing, feature importance, fold metrics, logs, and runtimes.
- `proposed_model_run/`: the broader panel features, price panel, OOF
  predictions, feature importance, and fold metrics.
- `architecture_sweep_50/`: architecture-search predictions, rankings,
  evaluations, variant catalog, and holdout outputs.

The model source is in `models/`, `experiments/`, and `src/`. The A100 workspace
did not contain serialized model-weight files such as `.pkl`, `.joblib`, `.cbm`,
or `.model`; the fitted models were used to generate the archived predictions
and metrics. The notebook contains the executable finalist fitting path.

Environment packages, virtual environments, Python caches, process IDs,
credentials, and temporary checkpoint files are intentionally excluded from
the archive.
