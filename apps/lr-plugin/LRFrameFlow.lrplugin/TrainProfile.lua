--[[ Library > Plug-in Extras > Train profile from selected photos...

The selected photos' current develop settings are what the profile learns. ]]

local LrApplication = import "LrApplication"
local LrBinding = import "LrBinding"
local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope = import "LrProgressScope"
local LrView = import "LrView"

local BridgeClient = require "BridgeClient"
local JobWait = require "JobWait"
local Log = require "Log"

local MIN_PHOTOS = 3

local GENRES = {
  { title = "Portrait", value = "portrait" },
  { title = "Wedding", value = "wedding" },
  { title = "Event", value = "event" },
  { title = "Business / corporate", value = "business" },
  { title = "Landscape", value = "landscape" },
  { title = "Product", value = "product" },
  { title = "Other", value = "other" },
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
      title = string.format(
        "LR-FrameFlow learns your look from the %d selected photos.\n" ..
        "Their current develop settings are the target, so pick finished edits.", count),
      height_in_lines = 2,
      width_in_chars = 52,
    },
    f:row {
      f:static_text { title = "Profile name:", alignment = "right", width = share "label" },
      f:edit_field { value = bind "name", width_in_chars = 30, immediate = true },
    },
    f:row {
      f:static_text { title = "Genre:", alignment = "right", width = share "label" },
      f:popup_menu { value = bind "genre", items = GENRES },
    },
    f:row {
      f:static_text { title = "Color:", alignment = "right", width = share "label" },
      f:popup_menu {
        value = bind "colorType",
        items = { { title = "Color", value = "color" }, { title = "Black & white", value = "bw" } },
      },
    },
  }

  local answer = LrDialogs.presentModalDialog {
    title = "LR-FrameFlow: Train profile",
    contents = contents,
    actionVerb = "Train",
  }
  if answer ~= "ok" then return nil end
  local name = (props.name or ""):gsub("^%s+", ""):gsub("%s+$", "")
  if name == "" then
    LrDialogs.message("Please enter a profile name.", nil, "warning")
    return nil
  end
  return { name = name, genre = props.genre, colorType = props.colorType }
end

LrFunctionContext.postAsyncTaskWithContext("LRFrameFlow.train", function(context)
  LrDialogs.attachErrorDialogToFunctionContext(context)

  local photos = LrApplication.activeCatalog():getTargetPhotos()
  if #photos < MIN_PHOTOS then
    LrDialogs.message("Select at least " .. MIN_PHOTOS .. " edited photos.",
      "The profile learns from your finished edits. More photos give better results.", "info")
    return
  end

  local _, err = BridgeClient.health()
  if err then
    LrDialogs.message("LR-FrameFlow", err, "critical")
    return
  end

  local choice = askForProfile(context, #photos)
  if not choice then return end

  local progress = LrProgressScope {
    title = "LR-FrameFlow: training \"" .. choice.name .. "\"",
    functionContext = context,
  }

  local reg, regErr = JobWait.registerPhotos(photos, progress)
  if not reg then
    if regErr ~= "canceled" then LrDialogs.message("LR-FrameFlow", regErr, "critical") end
    return
  end
  if reg.formats.raw and reg.formats.jpeg_tiff then
    LrDialogs.message("Mixed file types",
      "Please train RAW photos and JPEG/TIFF photos as separate profiles.", "warning")
    return
  end
  if #reg.uuids < MIN_PHOTOS then
    LrDialogs.message("Not enough usable photos",
      string.format("%d of the selected photos can be used (videos and other files are skipped).",
        #reg.uuids), "warning")
    return
  end

  local job, jobErr = BridgeClient.queueTrain {
    schema_version = "bridge-train-v1",
    profile_name = choice.name,
    genre = choice.genre,
    format_type = reg.formats.raw and "raw" or "jpeg_tiff",
    color_type = choice.colorType,
    lr_catalog_uuids = reg.uuids,
  }
  if not job then
    LrDialogs.message("LR-FrameFlow", jobErr, "critical")
    return
  end
  Log.info("train job %s queued with %d photos", job.job_id, #reg.uuids)

  local final, waitErr = JobWait.waitForJob(job.job_id, progress, "Training")
  progress:done()
  if not final then
    if waitErr == "canceled" then
      LrDialogs.message("Training continues in the background",
        "The Bridge keeps working on it. The profile appears in \"Apply profile\" once it is ready.",
        "info")
    else
      LrDialogs.message("LR-FrameFlow", waitErr, "critical")
    end
    return
  end
  if final.status == "completed" then
    LrDialogs.message("Profile \"" .. choice.name .. "\" is ready",
      "Select photos and use \"Apply profile to selected photos...\".", "info")
  else
    LrDialogs.message("Training failed", final.last_error or "No reason given.", "critical")
  end
end)
