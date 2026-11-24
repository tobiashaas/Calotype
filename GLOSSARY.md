# Calotype

An open darkroom that learns a photographer's way of editing — exposure, white balance, look, retouch, straightening, culling — and applies it to new photos in Lightroom Classic or on plain RAW + XMP folders.

## Photos and settings

**Photo**:
One original image the photographer works on (RAW, JPEG or TIFF), known by its catalog identity.
_Avoid_: image, file, picture

**Develop settings**:
Everything Lightroom stores about how a Photo is rendered: sliders, curves, colour, masks, crop.
_Avoid_: edit, adjustments, XMP (the sidecar is only one place they live)

**Slider**:
One of the per-photo values Calotype predicts: exposure, temperature, tint, contrast, highlights, shadows, whites, blacks, vibrance, saturation.
_Avoid_: param, parameter, setting

**Untouched**:
A Photo whose Develop settings are still what import gave it (defaults or the Import preset); the photographer has not decided anything on it yet.
_Avoid_: unedited, raw state

**Edited photo**:
A Photo whose Develop settings differ from the untouched state of its selection: the photographer decided something.
_Avoid_: processed, done

## White balance

**As shot**:
The camera's own white balance for a Photo; keeping it means the photographer accepted the camera's judgement of the light.
_Avoid_: auto, default WB

**Own white balance**:
A Kelvin and tint the photographer (or Calotype) set instead of As shot.
_Avoid_: custom WB, manual WB

**EXIF snapshot**:
What the camera recorded for a Photo: capture time, exposure settings (ISO, shutter time, aperture, exposure compensation) and the Measured colour temperature.
_Avoid_: metadata (that also covers the photographer's Decisions)

**Measured colour temperature**:
The camera's automatic estimate of the light for each frame, recorded even when the camera was set to a fixed white balance.
_Avoid_: as-shot Kelvin (that is the camera's setting, not its measurement)

## Learning a style

**Profile**:
What Calotype has learned from one photographer's Edited photos for one way of working; it predicts Sliders for new Photos and keeps the Recipe. One Profile keeps learning — it is retrained, not replaced.
_Avoid_: preset, model (the model is only part of a Profile), style

**Training photo**:
An Edited photo a Profile learns from, always with its current Develop settings.
_Avoid_: sample, example (an Example is a different thing)

**Recipe**:
The Slider values the photographer gives almost every Photo of a style unchanged (e.g. contrast −36, shadows +45); a Profile keeps them as they are instead of predicting them.
_Avoid_: base, defaults, constants

**Placeholder**:
A value an Import preset leaves on Photos the photographer never decided on (e.g. highlights −100); it teaches nothing about the photographer.
_Avoid_: untouched value, default

**Retrain**:
Teaching an existing Profile again from all its Training photos plus new ones, so the photographer's Corrections become part of it.
_Avoid_: new training, re-create

**Correction**:
A change the photographer makes to a Photo after Calotype applied a Profile; the strongest signal a Profile can learn from.
_Avoid_: fix, feedback (feedback also covers photos left as they are)

## Looks and presets

**Look**:
The rendering beyond the Sliders — tone curve, HSL, colour grading, grain, vignette, glow — that a style shares across its Photos.
_Avoid_: style layer, preset (a preset is only one way to carry a Look)

**Look preset**:
One of the photographer's installed Lightroom develop presets chosen to supply the Look.
_Avoid_: base preset

**Import preset**:
The develop preset Lightroom applies on import; the source of Placeholders.

**Retouch kind**:
One kind of AI mask Calotype retouches and learns: subject, sky, background, skin, eyes, teeth. Each has one Retouch preset and one title in the plugin.

**Retouch preset**:
A Calotype preset that adds one AI-mask Correction (one Retouch kind) with Mask strengths.
_Avoid_: mask preset

**Mask strength**:
The local slider values the photographer uses inside one kind of AI mask.

## A shoot

**Shoot**:
The Photos of one occasion (a wedding, a client job) edited together, usually one folder or collection.
_Avoid_: session, job, event

**Scene**:
Photos of a Shoot taken close in time under the same light (the hut, the evening reception); the photographer edits a Scene alike.
_Avoid_: series (a Series is narrower)

**Series**:
Consecutive, near-identical frames of one moment; they should look the same after editing.
_Avoid_: burst, sequence

**Example**:
An Edited photo inside the current selection that shows the Shoot's look to the Photos around it; it is not changed when Calotype applies.
_Avoid_: reference, training photo

**Shoot calibration**:
Adapting predictions to one Shoot from its Examples, instead of relying on the Profile alone.
_Avoid_: few-shot, learn from edits

**Apply**:
Writing Calotype's predicted Develop settings onto selected Photos.
_Avoid_: run, predict (prediction is only the first half)

**Fresh start**:
Resetting selected Photos to neutral before a Profile is applied, after saving their previous state.
_Avoid_: reset

**Straighten**:
Levelling a Photo from its own lines and cropping it the way Lightroom would.
_Avoid_: rotate, auto-upright

**Own crop**:
A crop or Straighten the photographer already gave a Photo; Straighten never replaces it, the Photo keeps it.
_Avoid_: existing crop

**Edit plan**:
What each Photo of an Apply gets — its Develop settings and Mask strengths — decided from the Profile, the Examples, the Look and the chosen options, in a fixed order.
_Avoid_: pipeline, inference (the prediction is only its first step)

## Culling

**Culling**:
Sorting a Shoot's Photos into Keep, Check and Sort out, with a reason for each.
_Avoid_: selection, rating

**Bucket**:
One of the three culling outcomes: Keep, Check, Sort out.
_Avoid_: class, category

**Decision**:
The photographer's own verdict on a Photo (pick flag or stars) that Culling learns from.
_Avoid_: label, rating

## Where it runs

**Bridge**:
The local program on the photographer's machine that reads Photos, keeps the outbox and talks to the server; the Lightroom plugin talks only to it.
_Avoid_: agent, daemon, desktop app (the app is the Bridge with a window)

**Dead-letter queue**:
Where a job message goes that a worker cannot run (unreadable, wrong kind, or failed), with the reason, so nothing is dropped silently.
_Avoid_: error queue, trash

**Failure code**:
Why a job failed, as a short fixed word (for example "no examples") that the plugin turns into its own hint; the failure reason is the text for people.
_Avoid_: error type, status

**Stuck job**:
A running job that has shown no progress for ten minutes; it goes back to the queue where its work starts.
_Avoid_: hung job, zombie

**Folder mode**:
Working on plain RAW + XMP folders without Lightroom.
_Avoid_: standalone, CLI mode

**Preview**:
The unedited image of a Photo the server learns and predicts from (the RAW's embedded JPEG or the original JPEG / TIFF), stored once per Photo.
_Avoid_: thumbnail, render, export

**Sidecar**:
The XMP file next to a RAW that carries its Develop settings in folder mode.
