# culling

Merkmale für die Bildauswahl und ein erklärbarer Start-Bewerter
([ADR 005](../../docs/adr/005-culling-architecture.md)). Reine Bildanalyse auf der
Bridge-Vorschau (≤ 1200 px, aufrecht, unbearbeitet) — keine DB, kein Redis.

| Modul | Inhalt |
|---|---|
| `technical.py` | Schärfe (Laplace-Varianz, feste Messgröße, kleine Regionen nie hochskaliert), Belichtung/Clipping, dHash |
| `faces.py` | YuNet findet Gesichter, MediaPipe liest je Gesicht Augen zu, Lächeln, Mund offen (Blendshapes) |
| `analyze.py` | `PhotoFeatures` pro Foto: relevante Gesichter, Motiv-Schärfe, Clipping auf dem Gesicht |
| `scoring.py` | Serien (aufeinanderfolgende ähnliche Bilder), Start-Bewerter mit Begründungen, Körbe keep/uncertain/reject |
| `learned.py` | Gelernter Bewerter: logistische Regression über dieselben Merkmale, trainiert aus Entscheidungen (Sterne/Picks); Erklärungen beschreiben das Foto („+ großes Gesicht; + Augen offen") |
| `models.py` | Re-Export der Modell-Registry aus `inference-pipeline` (SHA-256, [THIRD_PARTY_MODELS.md](../../THIRD_PARTY_MODELS.md)) |

Regeln des Start-Bewerters (die Gewichte werden später aus deinen Sternen/Markierungen gelernt):

- Technische Mängel sind Belege, kein Veto — ein starker Ausdruck halbiert den Unschärfe-Abzug.
- Lachen mit geschlossenen Augen ist ein Moment, kein Fehler.
- Schärfe zählt relativ zum Shooting (gleiche Werte = gleicher Rang, ab 5 Fotos).
- Helles Fenster im Hintergrund ist kein Fehler, ein ausgefressenes Gesicht schon.
- In einer Serie gewinnt das beste Bild; die anderen landen in „uncertain", nicht im Müll.

```bash
pip install -e libs/culling
python tools/lrff_eval/cull_report.py <vorschau-ordner>   # Kontaktbogen (HTML, lokal) + Zeiten
pytest libs/culling/tests
```

Benchmark gegen den Cull eines anderen Tools (1.837 Fotos, 367 zurückgehalten): Start-Gewichte
ROC-AUC 0,42 (schlechter als Zufall für diesen Shoot), gelernte Gewichte 0,74, Übereinstimmung
46 % → 71 % (`tools/lrff_eval/cull_learn.py`). Geschmack lässt sich nicht vorgeben — er wird gelernt.

Gemessen auf 60 Canon-CR3-Vorschauen (Business-Shooting): ~130 ms pro Foto auf CPU,
Modelle laden in ~2 s.
