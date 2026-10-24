FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv \
    PASARPULSE_MODE=auto
WORKDIR /srv

COPY requirements-runtime.txt /srv/requirements-runtime.txt
RUN pip install --no-cache-dir --default-timeout=120 -r /srv/requirements-runtime.txt

COPY app /srv/app
COPY demo_data /srv/demo_data
COPY results/summary_metrics.csv /srv/results/summary_metrics.csv
COPY results/finalist_pooled_metrics.csv /srv/results/finalist_pooled_metrics.csv
COPY results/meta_metrics.csv /srv/results/meta_metrics.csv
COPY results/proposed_model_run/pooled_metrics.csv /srv/results/proposed_model_run/pooled_metrics.csv
COPY results/multimodal_ablation/pooled_metrics.csv /srv/results/multimodal_ablation/pooled_metrics.csv
COPY results/clean_metrics/early_warning_metrics.csv /srv/results/clean_metrics/early_warning_metrics.csv

COPY results/dashboard_xai/forecast_top5.csv /srv/results/dashboard_xai/forecast_top5.csv
COPY results/dashboard_xai/manifest.json /srv/results/dashboard_xai/manifest.json

EXPOSE 8000
CMD ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
