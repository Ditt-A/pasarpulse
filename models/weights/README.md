# PasarPulse winning model weights

These are the fitted LightGBM weights for the validated `expert_lgb_logratio`
model. They were trained on the complete audited price panel through 2026-07-31
using the validated 157-feature order and the parameters recorded in
`model_manifest.json`.

| Forecast horizon | Weight file | Training rows | Series | Validated pooled MAE |
|---:|---|---:|---:|---:|
| 7 days | `expert_lgb_logratio_7d.txt` | 178,734 | 280 | Rp3,275.46/kg |
| 14 days | `expert_lgb_logratio_14d.txt` | 177,167 | 280 | Rp4,882.06/kg |

The files are native LightGBM text boosters and can be loaded with:

```python
import numpy as np
from lightgbm import Booster

model = Booster(model_file="models/weights/expert_lgb_logratio_7d.txt")
prediction_logratio = model.predict(encoded_feature_frame)
prediction_price = (current_price * np.exp(np.clip(prediction_logratio, -1.2, 1.2)))
prediction_price = np.clip(prediction_price, 1000, 500000)
```

`model_manifest.json` is required for deployment. It contains the exact feature
order, categorical mappings, training date range, hashes, and serialization
checks. The categorical columns must be encoded with those saved mappings before
calling `Booster.predict`.

`training_summary.csv` records the final-fit provenance. Both boosters were
loaded after serialization on the A100 and reproduced the in-memory prediction
with maximum absolute difference `0.0`.
