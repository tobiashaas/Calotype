--[[ Library > Plug-in Extras > Train profile from selected photos...

The selected photos' current develop settings are what the profile learns. ]]

local LrApplication = import "LrApplication"
local LrBinding = import "LrBinding"
local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope = import "LrProgressScope"
local LrView = import "LrView"

local Actions = require "Actions"
local BridgeClient = require "BridgeClient"

local GENRES = {
  { title = LOC "$$$/Tarsier/Genre/Portrait=Portrait", value = "portrait" },
  { title = LOC "$$$/Tarsier/Genre/Wedding=Wedding", value = "wedding" },
  { title = LOC "$$$/Tarsier/Genre/Event=Event", value = "event" },
  { title = LOC "$$$/Tarsier/Genre/Business=Business / corporate", value = "business" },
  { title = LOC "$$$/Tarsier/Genre/Landscape=Landscape", value = "landscape" },
  { title = LOC "$$$/Tarsier/Genre/Product=Product", value = "product" },
  { title = LOC "$$$/Tarsier/Genre/Other=Other", value = "other" },
}

local function askForProfile(context, count)
  local f = LrView.osFactory()
  local bind = LrView.bind
  local share = LrView.share
  local props = LrBinding.makePropertyTable(context)
  props.name = ""
  props.genre = "portrait"
  props.colorType = "color"

  local contents = f:column {
    bind_to_object = props,
    spacing = f:control_spacing(),
    f:static_text {
      title = LOC("$$$/Tarsier/Train/Intro=Tarsier learns your look from the ^1 selected photos.^nTheir current develop settings are the target, so pick finished edits.", count),
      height_in_lines = 2,
      width_in_chars = 52,
    },
    f:row {
      f:static_text { title = LOC "$$$/Tarsier/Train/Name=Profile name:", alignment = "right", width = share "label" },
      f:edit_field { value = bind "name", width_in_chars = 30, immediate = true },
    },
    f:row {
      f:static_text { title = LOC "$$$/Tarsier/Train/Genre=Genre:", alignment = "right", width = share "label" },
      f:popup_menu { value = bind "genre", items = GENRES },
    },
    f:row {
      f:static_text { title = LOC "$$$/Tarsier/Train/Color=Color:", alignment = "right", width = share "label" },
      f:popup_menu {
        value = bind "colorType",
        items = {
          { title = LOC "$$$/Tarsier/Train/ColorColor=Color", value = "color" },
          { title = LOC "$$$/Tarsier/Train/ColorBW=Black & white", value = "bw" },
        },
      },
    },
  }

  local answer = LrDialogs.presentModalDialog {
    title = LOC "$$$/Tarsier/Train/Title=Tarsier: Train profile",
    contents = contents,
    actionVerb = LOC "$$$/Tarsier/Train/Action=Train",
  }
  if answer ~= "ok" then return nil end
  local name = (props.name or ""):gsub("^%s+", ""):gsub("%s+$", "")
  if name == "" then
    LrDialogs.message(LOC "$$$/Tarsier/Train/NoName=Please enter a profile name.", nil, "warning")
    return nil
  end
  return { name = name, genre = props.genre, colorType = props.colorType }
end

LrFunctionContext.postAsyncTaskWithContext("Tarsier.train", function(context)
  LrDialogs.attachErrorDialogToFunctionContext(context)

  local photos = LrApplication.activeCatalog():getTargetPhotos()
  if #photos < Actions.MIN_TRAIN_PHOTOS then
    LrDialogs.message(LOC("$$$/Tarsier/Train/TooFew=Select at least ^1 edited photos.", Actions.MIN_TRAIN_PHOTOS),
      LOC "$$$/Tarsier/Train/TooFewHint=The profile learns from your finished edits. More photos give better results.",
      "info")
    return
  end

  local _, err = BridgeClient.health()
  if err then
    LrDialogs.message("Tarsier", err, "critical")
    return
  end

  local choice = askForProfile(context, #photos)
  if not choice then return end

  local progress = LrProgressScope {
    title = LOC("$$$/Tarsier/Train/Progress=Tarsier: training \"^1\"", choice.name),
    functionContext = context,
  }
  local result = Actions.train(photos, choice, progress)
  progress:done()
  if not result.canceled or result.title ~= "Tarsier" then
    LrDialogs.message(result.title, result.text, result.level)
  end
end)
