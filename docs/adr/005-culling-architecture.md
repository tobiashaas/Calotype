# ADR 005 — Culling: viele erklärbare Merkmale, gewichtet nach dem Geschmack des Fotografen

- **Status:** Vorschlag
- **Datum:** 2026-11-06
- **Entscheider:** Maintainer
- **Baut auf:** [ADR 004](004-bridge-localhost-architecture.md) (Bridge, Vorschau aus dem Original)

## Kontext

Culling = aus hunderten oder tausenden Fotos eines Shootings die behaltenswerten finden.
Starre Regeln („unscharf = raus", „Augen zu = raus") scheitern genau an den Bildern, die
Fotografen am meisten schätzen: ein leicht unscharfer Moment voller Emotion, ein Lachen mit
geschlossenen Augen. Gute Werkzeuge am Markt zerlegen das Problem in viele spezialisierte
Bewertungen und kombinieren sie in einem einfachen, erklärbaren Modell (Architektur-Erkenntnis,
keine Übernahme fremder Modelle oder Werte).

**Kernanforderung:** Technische Mängel sind *Merkmale*, kein Veto. Ob ein emotional starkes,
technisch schwaches Bild bleibt, entscheidet der gelernte Geschmack des Fotografen.

## Entscheidung

### 1. Merkmale pro Bild (alle aus der Bridge-Vorschau, ≤ 1200 px)

| Gruppe | Beispiele |
|---|---|
| Technik | Schärfe gesamt und auf dem Hauptmotiv, Bewegungsunschärfe, Belichtung/Clipping, Rauschen |
| Gesicht (je Gesicht, dann bestes/Mittel/Max pro Bild) | Größe, Schärfe der Augenregion, Augen offen (Lidabstand aus Landmarks), Blickrichtung, Kopfhaltung |
| Moment & Emotion | Gesichtsausdruck (Lachen, Weinen, Überraschung), Intensität, Interaktion (Umarmung, Kuss, Blickkontakt), spontan vs. gestellt, Körperhaltung |
| Inhalt | Bild-Embedding (z. B. CLIP/DINOv2) und Text-Ähnlichkeiten („spontaner Moment voller Freude", „Detailaufnahme", „Gruppenfoto") |
| Serie | Gruppierung nahezu gleicher Bilder über Embeddings + Zeitstempel; Merkmale *relativ zur Serie* (schärfstes, emotionalstes, offenste Augen der Serie) |

Kombinationen wie „lacht mit geschlossenen Augen" sind eigene Merkmale, damit sie nicht als
„Augen zu" bestraft werden.

### 2. Bewertungsmodell: gelernt aus den Entscheidungen des Fotografen

- Kleines, erklärbares Modell (zunächst logistische Regression bzw. Gradient Boosting) über
  die normierten Merkmale; Ausgabe: Wahrscheinlichkeit „behalten".
- **Trainingsdaten sind vorhandene Entscheidungen:** Sterne, Pick/Reject, Farbmarkierungen,
  exportierte Fotos aus Lightroom-Katalogen (Plugin liest sie) bzw. `xmp:Rating` aus Sidecars.
- Pro Profil/Genre eigene Gewichte (Hochzeit ≠ Business-Porträt).
- Kalibrierung der Rohmerkmale gegen die eigene Fotosammlung (Perzentile), damit Schwellen
  kameraübergreifend dasselbe bedeuten.

### 3. Ergebnis: vorsortieren, begründen, unsichere Fälle zeigen

- Drei Körbe: **behalten**, **aussortieren**, **unsicher** (nahe der Entscheidungsgrenze) — der
  Fotograf schaut vor allem in „unsicher".
- Jede Entscheidung mit Begründung aus den stärksten Merkmalen, z. B. „behalten: starkes
  Lachen, Interaktion; leichte Unschärfe" oder „aussortiert: Augen zu, kein Ausdruck,
  schärferes Bild derselben Serie vorhanden".
- Rückgabe in Lightroom als Sterne/Markierungen/Farbetiketten (Plugin) bzw. `xmp:Rating`/
  `xmp:Label` (Ordner-Modus).

### 4. Messung (`lrff-eval cull`)

Maßstab sind die Entscheidungen des Fotografen, getrennt in Trainings- und Testmenge:

- Übereinstimmung gesamt (Precision/Recall für „behalten").
- **Gerettete Ausnahmen:** Anteil der technisch schwachen (unscharf/Augen zu), aber behaltenen
  Bilder, die das Modell ebenfalls behält — die Kennzahl für die Kernanforderung.
- Stufen einzeln: Gesichtserkennung, Augen offen/zu, Unschärfe gegen markierte Stichprobe.
- Zeit pro Foto, Modellgröße.

### 5. Modelle austauschbar, Repo nur mit freien Lizenzen

- Jede Stufe hinter einer Schnittstelle (`face_detector`, `landmarks`, `embedding`, …),
  Auswahl per Konfiguration.
- Im Repo und in Releases nur Modelle mit **MIT/Apache-2.0/BSD**-Lizenz für Code *und*
  Gewichte; jedes Modell steht mit Quelle und Lizenz in `THIRD_PARTY_MODELS.md`.
- Nicht-kommerzielle oder Copyleft-Modelle (z. B. AGPL) können lokal eingehängt werden,
  werden aber nie mitgeliefert. Modelle oder Werte anderer Produkte werden nicht verwendet.
- `lrff-eval` vergleicht Modelle auf den eigenen Fotos, bevor ein Standard gewechselt wird.

## Folgen / Trade-offs

- **Positiv:** Erklärbar und korrigierbar; lernt den persönlichen Geschmack aus Daten, die
  Fotografen ohnehin haben; einzelne Stufen sind unabhängig austausch- und messbar.
- **Negativ / Risiken:** Viele Modelle = mehr Rechenzeit pro Foto (Ziel: < 1 s auf CPU,
  Vorschau 1200 px reicht für Gesichter ab ~40 px). Emotion/Interaktion sind die schwierigsten
  Merkmale; ohne genug eigene Entscheidungen (< ~500 Bilder) bleibt das Modell grob — dann
  Startgewichte pro Genre, die mit jeder Korrektur besser werden.
- **Offen:** Wo laufen die Modelle — Worker (Server) oder Bridge (lokal, ONNX)? Für große
  Shootings und Datenschutz spricht lokal; Entscheidung nach ersten Laufzeitmessungen.
