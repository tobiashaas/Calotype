--[[ Start from zero: reset photos before a profile is applied to them.

A profile writes only the sliders it predicts and the look it carries. What an earlier edit
left on a photo — another preset's color grading, a curve, masks, a crop — would stay and mix
with the new look. So "start from zero" first puts every selected photo back to neutral:
tone and color sliders, curves, color mixer, color grading, grain, vignette, sharpening,
crop and all masks and local corrections. Lens corrections, transform and spot removal stay.

The state before is kept on every photo as a develop snapshot "Calotype: before reset <date>".
The SDK has no reset for photos outside the Develop module, so the neutral values are set
explicitly. Call only inside an async task. ]]

local LrTasks = import "LrTasks"

local Fresh = {}

local COLORS = { "Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta" }
local LOCAL = { "MaskGroupBasedCorrections", "GradientBasedCorrections",
                "CircularGradientBasedCorrections", "PaintBasedCorrections" }

--- Lightroom's neutral develop settings for everything a profile or a look may set.
function Fresh.neutral()
  local s = {
    WhiteBalance = "As Shot",
    Exposure2012 = 0, Contrast2012 = 0, Highlights2012 = 0, Shadows2012 = 0, Whites2012 = 0,
    Blacks2012 = 0, Texture = 0, Clarity2012 = 0, Dehaze = 0, Vibrance = 0, Saturation = 0,
    ParametricShadows = 0, ParametricDarks = 0, ParametricLights = 0, ParametricHighlights = 0,
    ParametricShadowSplit = 25, ParametricMidtoneSplit = 50, ParametricHighlightSplit = 75,
    ToneCurveName2012 = "Linear",
    ToneCurvePV2012 = { 0, 0, 255, 255 }, ToneCurvePV2012Red = { 0, 0, 255, 255 },
    ToneCurvePV2012Green = { 0, 0, 255, 255 }, ToneCurvePV2012Blue = { 0, 0, 255, 255 },
    ConvertToGrayscale = false,
    ColorGradeMidtoneHue = 0, ColorGradeMidtoneSat = 0, ColorGradeMidtoneLum = 0,
    ColorGradeShadowLum = 0, ColorGradeHighlightLum = 0, ColorGradeBlending = 50,
    ColorGradeGlobalHue = 0, ColorGradeGlobalSat = 0, ColorGradeGlobalLum = 0,
    SplitToningShadowHue = 0, SplitToningShadowSaturation = 0, SplitToningHighlightHue = 0,
    SplitToningHighlightSaturation = 0, SplitToningBalance = 0,
    GrainAmount = 0, PostCropVignetteAmount = 0,
    Sharpness = 40, SharpenRadius = 1, SharpenDetail = 25, SharpenEdgeMasking = 0,
    LuminanceSmoothing = 0, ColorNoiseReduction = 25,
    CropLeft = 0, CropTop = 0, CropRight = 1, CropBottom = 1, CropAngle = 0, HasCrop = false,
  }
  for _, color in ipairs(COLORS) do
    s["HueAdjustment" .. color] = 0
    s["SaturationAdjustment" .. color] = 0
    s["LuminanceAdjustment" .. color] = 0
  end
  return s
end

--- First write transaction: keep the original as a snapshot and take off masks and local
-- corrections. Removing masks must not share a transaction with adding new ones (Retouch.lua).
function Fresh.clear(photo, stamp)
  -- A snapshot of its own per reset: "Calotype: before" may exist from an earlier run and
  -- then holds an older state than the one that is about to be replaced.
  if photo.createDevelopSnapshot then
    LrTasks.pcall(function() photo:createDevelopSnapshot(Fresh.snapshotName(stamp), false) end)
  end
  local current = photo:getDevelopSettings() or {}
  local empty, any = {}, false
  for _, key in ipairs(LOCAL) do
    if type(current[key]) == "table" and next(current[key]) ~= nil then
      empty[key], any = {}, true
    end
  end
  if any then photo:applyDevelopSettings(empty) end
end

--- Second write transaction: every slider back to neutral.
function Fresh.reset(photo)
  local settings = Fresh.neutral()
  for key, value in pairs(photo:getDevelopSettings() or {}) do
    -- Lightroom 16 glow: its keys start with "Glow"; whatever is set goes back to 0.
    if type(key) == "string" and key:sub(1, 4) == "Glow" and type(value) == "number" then
      settings[key] = 0
    end
  end
  photo:applyDevelopSettings(settings)
end

--- Name of the snapshot that keeps the state before a reset, e.g. "Calotype: before reset
-- 2026-11-22 14:05".
function Fresh.snapshotName(stamp)
  return LOC("$$$/Calotype/Fresh/Snapshot=Calotype: before reset ^1", stamp or os.date("%Y-%m-%d %H:%M"))
end

--- Reset all `photos` in two write transactions. Returns how many were reset and the name
-- of the snapshot that keeps the state before.
function Fresh.start(catalog, photos)
  local stamp = os.date("%Y-%m-%d %H:%M")
  catalog:withWriteAccessDo(LOC "$$$/Calotype/Fresh/Clear=Calotype: remove masks", function()
    for _, photo in ipairs(photos) do Fresh.clear(photo, stamp) end
  end, { timeout = 60 })
  catalog:withWriteAccessDo(LOC "$$$/Calotype/Fresh/Reset=Calotype: start from zero", function()
    for _, photo in ipairs(photos) do Fresh.reset(photo) end
  end, { timeout = 60 })
  return #photos, Fresh.snapshotName(stamp)
end

return Fresh
