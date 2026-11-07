# edit-serializer

Translates between the internal model parameters and Lightroom Classic develop settings.
Pure transformation, no dependencies.

| Direction | Function | Use |
|---|---|---|
| Lightroom → internal | `from_lightroom(settings, format_type)` | Train worker: training targets from `photo:getDevelopSettings()` |
| internal → Lightroom | `to_lightroom(params, format_type)` / `serialize_for_lightroom` | Inference worker: values for `photo:applyDevelopSettings()` |

`to_lightroom` clamps every value to the slider range and rounds to Lightroom's
precision (exposure 2 decimal places, otherwise whole numbers).

| internal | RAW | JPEG/TIFF | Range |
|---|---|---|---|
| `exposure` | `Exposure2012` | `Exposure2012` | −5 … +5 |
| `temp` | `Temperature` (Kelvin) | `IncrementalTemperature` | 2000 … 50000 / −100 … +100 |
| `tint` | `Tint` | `IncrementalTint` | −150 … +150 / −100 … +100 |
| `contrast`, `highlights`, `shadows`, `whites`, `blacks` | `*2012` | `*2012` | −100 … +100 |
| `vibrance`, `saturation` | `Vibrance`, `Saturation` | same | −100 … +100 |

Missing Lightroom values count as neutral (0). Exception: for RAW there is no sensible default
for a missing `Temperature` — the photo is then not used for training.

```bash
pip install -e "libs/edit-serializer[dev]"
pytest libs/edit-serializer/tests
```
