--[[ Library > Plug-in Extras > Train profile from selected photos...

The selected photos' current develop settings are what the profile learns. A new profile, or
keep training a ready one (one living profile per look): then the photos the photographer
corrected after Calotype applied it are learned, and photos left as Calotype set them only when
they carry the photographer's marker (Markers.lua) — the profile must not learn from itself. ]]

local LrApplication = import "LrApplication"
local LrBinding = import "LrBinding"
local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope = import "LrProgressScope"
local LrView = import "LrView"

local Actions = require "Actions"
local BridgeClient = require "BridgeClient"
local LookPresets = require "LookPresets"
local Markers = require "Markers"

local GENRES = {
  { title = LOC "$$$/Calotype/Genre/Portrait=Portrait", value = "portrait" },
  { title = LOC "$$$/Calotype/Genre/Wedding=Wedding", value = "wedding" },
  { title = LOC "$$$/Calotype/Genre/Event=Event", value = "event" },
  { title = LOC "$$$/Calotype/Genre/Business=Business / corporate", value = "business" },
  { title = LOC "$$$/Calotype/Genre/Landscape=Landscape", value = "landscape" },
  { title = LOC "$$$/Calotype/Genre/Product=Product", value = "product" },
  { title = LOC "$$$/Calotype/Genre/Other=Other", value = "other" },
}

local NEW = ""

--- The train dialog: a new profile, or keep training one of the ready profiles (its
-- corrections, and accepted photos by the photographer's marker). Returns the choice for
-- Actions.train or nil.
local function askForProfile(context, count, readyItems)
  local f = LrView.osFactory()
  local bind = LrView.bind
  local share = LrView.share
  local props = LrBinding.makePropertyTable(context)
  props.target = NEW
  props.name = ""
  props.genre = "portrait"
  props.colorType = "color"
  props.look = ""
  props.importPreset = ""
  props.marker = "none"
  local looks = { { title = LOC "$$$/Calotype/Look/None=None (only what the photos show)", value = "" } }
  local presets = { { title = LOC "$$$/Calotype/Train/ImportPresetNone=None", value = "" } }
  for _, item in ipairs(LookPresets.items()) do
    looks[#looks + 1] = item
    presets[#presets + 1] = item
  end
  local targets = { { title = LOC "$$$/Calotype/Train/New=New profile", value = NEW } }
  local profiles = {}
  for _, item in ipairs(readyItems) do
    targets[#targets + 1] = { title = LOC("$$$/Calotype/Train/KeepTraining=Keep training: ^1", item.title), value = item.value }
    profiles[item.value] = item.profile
  end
  -- Keep training: the marker the profile was trained with last time.
  props:addObserver("target", function(_, _, value)
    local profile = profiles[value]
    props.marker = Markers.toValue(profile and profile.accepted_marker)
  end)
  local isNew = LrBinding.keyEquals("target", NEW)

  local contents = f:column {
    bind_to_object = props,
    spacing = f:control_spacing(),
    f:static_text {
      title = LOC("$$$/Calotype/Train/Intro=Calotype learns your look from the ^1 selected photos.^nTheir current develop settings are the target, so pick finished edits.", count),
      height_in_lines = 2,
      width_in_chars = 52,
    },
    f:row {
      f:static_text { title = LOC "$$$/Calotype/Train/Target=Profile:", alignment = "right", width = share "label" },
      f:popup_menu { value = bind "target", items = targets, width_in_chars = 36 },
    },
    f:row {
      f:static_text { title = LOC "$$$/Calotype/Train/Name=Profile name:", alignment = "right", width = share "label" },
      f:edit_field { value = bind "name", width_in_chars = 30, immediate = true, enabled = isNew },
    },
    f:row {
      f:static_text { title = LOC "$$$/Calotype/Train/Genre=Genre:", alignment = "right", width = share "label" },
      f:popup_menu { value = bind "genre", items = GENRES, enabled = isNew },
    },
    f:row {
      f:static_text { title = LOC "$$$/Calotype/Train/Color=Color:", alignment = "right", width = share "label" },
      f:popup_menu {
        value = bind "colorType",
        enabled = isNew,
        items = {
          { title = LOC "$$$/Calotype/Train/ColorColor=Color", value = "color" },
          { title = LOC "$$$/Calotype/Train/ColorBW=Black & white", value = "bw" },
        },
      },
    },
    f:row {
      f:static_text { title = LOC "$$$/Calotype/Look/Label=Look:", alignment = "right", width = share "label" },
      f:popup_menu { value = bind "look", items = looks, width_in_chars = 36 },
    },
    f:static_text {
      title = LOC "$$$/Calotype/Look/TrainHint=Optional: one of your presets as the profile's look. Exposure and white balance are still learned per photo.",
      width_in_chars = 52, height_in_lines = 2,
    },
    f:row {
      f:static_text { title = LOC "$$$/Calotype/Train/Marker=Accepted photos:", alignment = "right", width = share "label" },
      f:popup_menu { value = bind "marker", items = Markers.items(), width_in_chars = 24 },
    },
    f:static_text {
      title = LOC "$$$/Calotype/Train/MarkerHint=Photos Calotype edited and you left as they are teach the profile only if they carry this marker. Photos you changed afterwards always count as corrections.",
      width_in_chars = 52, height_in_lines = 3,
    },
    f:row {
      f:static_text { title = LOC "$$$/Calotype/Train/ImportPreset=Import preset:", alignment = "right", width = share "label" },
      f:popup_menu { value = bind "importPreset", items = presets, width_in_chars = 36 },
    },
    f:static_text {
      title = LOC "$$$/Calotype/Train/ImportPresetHint=Optional: the preset Lightroom applies on import. Values it left on a photo (e.g. highlights -100) are not taught as your decision.",
      width_in_chars = 52, height_in_lines = 2,
    },
  }

  local answer = LrDialogs.presentModalDialog {
    title = LOC "$$$/Calotype/Train/Title=Calotype: Train profile",
    contents = contents,
    actionVerb = LOC "$$$/Calotype/Train/Action=Train",
  }
  if answer ~= "ok" then return nil end
  local choice = {
    basePreset = LookPresets.settings(props.look),
    untouched = LookPresets.placeholders(props.importPreset),
    marker = Markers.fromValue(props.marker),
  }
  local profile = profiles[props.target]
  if profile then
    -- The server needs the request's name, genre and color; a retrain keeps the profile's.
    choice.profileId, choice.name = profile.profile_id, profile.name
    choice.genre, choice.colorType = profile.genre, profile.color_type
    return choice
  end
  local name = (props.name or ""):gsub("^%s+", ""):gsub("%s+$", "")
  if name == "" then
    LrDialogs.message(LOC "$$$/Calotype/Train/NoName=Please enter a profile name.", nil, "warning")
    return nil
  end
  choice.name, choice.genre, choice.colorType = name, props.genre, props.colorType
  return choice
end

LrFunctionContext.postAsyncTaskWithContext("Calotype.train", function(context)
  LrDialogs.attachErrorDialogToFunctionContext(context)

  local photos = LrApplication.activeCatalog():getTargetPhotos()
  if #photos < Actions.MIN_TRAIN_PHOTOS then
    LrDialogs.message(LOC("$$$/Calotype/Train/TooFew=Select at least ^1 edited photos.", Actions.MIN_TRAIN_PHOTOS),
      LOC "$$$/Calotype/Train/TooFewHint=The profile learns from your finished edits. More photos give better results.",
      "info")
    return
  end

  local _, err = BridgeClient.health()
  if err then
    LrDialogs.message("Calotype", err, "critical")
    return
  end

  -- Keep training is offered for ready profiles; without any, only a new profile.
  local readyItems = Actions.readyProfiles() or {}
  local choice = askForProfile(context, #photos, readyItems)
  if not choice then return end

  local progress = LrProgressScope {
    title = LOC("$$$/Calotype/Train/Progress=Calotype: training \"^1\"", choice.name),
    functionContext = context,
  }
  local result = Actions.train(photos, choice, progress)
  progress:done()
  if not result.canceled or result.title ~= "Calotype" then
    LrDialogs.message(result.title, result.text, result.level)
  end
end)
