# edit-serializer

Übersetzt zwischen den internen Modell-Parametern und Lightroom-Classic-Develop-Settings.
Reine Transformation, keine Abhängigkeiten.

| Richtung | Funktion | Einsatz |
|---|---|---|
| Lightroom → intern | `from_lightroom(settings, format_type)` | Train-Worker: Trainingsziele aus `photo:getDevelopSettings()` |
| intern → Lightroom | `to_lightroom(params, format_type)` / `serialize_for_lightroom` | Inference-Worker: Werte für `photo:applyDevelopSettings()` |

`to_lightroom` begrenzt jeden Wert auf den Regler-Bereich und rundet auf Lightrooms
Genauigkeit (Belichtung 2 Nachkommastellen, sonst ganze Zahlen).

| intern | RAW | JPEG/TIFF | Bereich |
|---|---|---|---|
| `exposure` | `Exposure2012` | `Exposure2012` | −5 … +5 |
| `temp` | `Temperature` (Kelvin) | `IncrementalTemperature` | 2000 … 50000 / −100 … +100 |
| `tint` | `Tint` | `IncrementalTint` | −150 … +150 / −100 … +100 |
| `contrast`, `highlights`, `shadows`, `whites`, `blacks` | `*2012` | `*2012` | −100 … +100 |
| `vibrance`, `saturation` | `Vibrance`, `Saturation` | gleich | −100 … +100 |

Fehlende Lightroom-Werte zählen als neutral (0). Ausnahme: Bei RAW gibt es für fehlende
`Temperature` keinen sinnvollen Standard — das Foto wird dann nicht zum Training genutzt.

```bash
pip install -e "libs/edit-serializer[dev]"
pytest libs/edit-serializer/tests
```
