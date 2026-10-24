from __future__ import annotations

from urllib.request import urlopen

_CORE_URL = "https://raw.githubusercontent.com/ElFariss/data-science-mcp/e34672212bc77310e90f5528170f15f7a529ee14/pasarpulse_compute/pasarpulse_optimizer.py"
_source = urlopen(_CORE_URL, timeout=120).read().decode("utf-8")
_source = _source.replace(
    'encoder.transform(train_frame[column].astype(str).fillna("missing")).astype("category")',
    'encoder.transform(train_frame[column].astype(str).fillna("missing")).astype("int32")',
).replace(
    'encoder.transform(test_frame[column].astype(str).fillna("missing")).astype("category")',
    'encoder.transform(test_frame[column].astype(str).fillna("missing")).astype("int32")',
)
exec(compile(_source, _CORE_URL, "exec"), globals(), globals())
