# Calotype — Website `calotype.xyz`

Die Website ist in Etch Studio gebaut (nicht in diesem Repository) und wird über Cloudflare
ausgeliefert. Diese Seite beschreibt die Gestaltungslinie, damit App, Plugin und Website
zusammenpassen.

## Gestaltungslinie „Kontaktbogen“

- **Ton:** du-Form, nüchtern, keine Werbefloskeln. Schwache Messwerte stehen neben den guten.
- **Farben:** warmes Fast-Schwarz als Grund, papierweißer Text, Bernstein (`#E6A23C`) nur für
  Markierungen und den einen Hauptbutton.
- **Schrift:** Overused Grotesk für Text und Überschriften, JetBrains Mono für Werte, Dateinamen
  und Beschriftungen. Beide OFL, selbst gehostet.
- **Form:** Haarlinien statt Karten, linksbündiges Raster, eckige Buttons mit Mono-Beschriftung.
- **Bilder:** Solange es keine freigegebenen Fotos gibt, stehen unscharfe Farbfelder für Fotos,
  darunter Dateiname und Reglerwerte. Keine gezeichneten Motive, keine fremden Fotos.
- **Bewegung:** Wort-Reveal im Titel, der Kontaktbogen wird nacheinander „bearbeitet“, Tabs und
  Accordion gleiten. Wer reduzierte Bewegung eingestellt hat, sieht nichts davon.

## Seiten

| Pfad | Inhalt |
|---|---|
| `/` | Einstieg mit Kontaktbogen, Funktionen (Bearbeiten, Sortieren, Retusche, Begradigen), Regler und XMP, Messwerte, Looks, Ablauf, Alternativen, Fragen, Roadmap, Ausprobieren |
| `/forschung/` | Die Paper hinter Calotype mit direkten Links (arXiv, DOI), Status genutzt / geplant |
| `/impressum/`, `/datenschutz/` | Rechtliches; keine Cookies, kein Tracking, Schriften und Skripte lokal |

## Regeln für Inhalte

- Zahlen zu Calotype nur aus eigenen Messungen (`tools/eval/`, `tools/lr_e2e/`).
- Andere Werkzeuge werden fair als Alternativen genannt, mit Quelle und Datum der Angaben.
- Geplantes steht unter „Roadmap“ und wird nicht als vorhanden beschrieben.
- Bezahlte Bausteine (Motion+, Hugeicons Pro) nur auf der Website, nie in diesem Repository
  oder in der App.
