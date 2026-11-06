--[[ Library > Plug-in Extras > Apply profile to selected photos...

Predicted settings are written with photo:applyDevelopSettings in one catalog
transaction, so Lightroom's history and Edit > Undo work as usual. ]]

local LrApplication = import "LrApplication"
local LrBinding = import "LrBinding"
local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope = import "LrProgressScope"
local LrView = import "LrView"

local BridgeClient = require "BridgeClient"
local JobWait = require "JobWait"
local Log = require "Log"
local PhotoData = require "PhotoData"

local FORMAT_TEXT = { raw = "RAW", jpeg_tiff = "JPEG/TIFF" }

local function readyProfiles()
  local profiles, err = BridgeClient.profiles()
  if not profiles then return nil, err end
  local items = {}
  for _, p in ipairs(profiles) do
    if p.status == "ready" then
      items[#items + 1] = {
        title = string.format("%s  (%s, %s, v%s)", p.name, p.genre,
          FORMAT_TEXT[p.format_type] or p.format_type, tostring(p.version)),
        value = p.profile_id,
        profile = p,
      }
    end
  end
  table.sort(items, function(a, b) return a.title:lower() < b.title:lower() end)
  return items
end

local function askForProfile(context, items, count)
  local f = LrView.osFactory()
  local props = LrBinding.makePropertyTable(context)
  props.profileId = items[1].value
  local answer = LrDialogs.presentModalDialog {
    title = "LR-FrameFlow: Apply profile",
    contents = f:column {
      bind_to_object = props,
      spacing = f:control_spacing(),
      f:static_text { title = string.format("Apply a profile to %d selected photos.", count) },
      f:popup_menu { value = LrView.bind "profileId", items = items, width_in_chars = 40 },
    },
    actionVerb = "Apply",
  }
  if answer ~= "ok" then return nil end
  for _, item in ipairs(items) do
    if item.value == props.profileId then return item.profile end
  end
  return nil
end

LrFunctionContext.postAsyncTaskWithContext("LRFrameFlow.apply", function(context)
  LrDialogs.attachErrorDialogToFunctionContext(context)
  local catalog = LrApplication.activeCatalog()

  local photos = catalog:getTargetPhotos()
  if #photos == 0 then
    LrDialogs.message("Select the photos you want to edit first.", nil, "info")
    return
  end

  local items, err = readyProfiles()
  if not items then
    LrDialogs.message("LR-FrameFlow", err, "critical")
    return
  end
  if #items == 0 then
    LrDialogs.message("No profile is ready yet",
      "Train one first with \"Train profile from selected photos...\".", "info")
    return
  end

  local profile = askForProfile(context, items, #photos)
  if not profile then return end

  -- Only photos of the profile's file type: RAW white balance (Kelvin) and JPEG
  -- white balance (relative) are different sliders.
  local matching, wrongType = {}, 0
  for _, photo in ipairs(photos) do
    if PhotoData.formatType(photo:getRawMetadata("fileFormat")) == profile.format_type then
      matching[#matching + 1] = photo
    else
      wrongType = wrongType + 1
    end
  end
  if #matching == 0 then
    LrDialogs.message("No matching photos",
      string.format("\"%s\" is a %s profile; none of the selected photos is %s.",
        profile.name, FORMAT_TEXT[profile.format_type], FORMAT_TEXT[profile.format_type]),
      "warning")
    return
  end

  local progress = LrProgressScope {
    title = "LR-FrameFlow: applying \"" .. profile.name .. "\"",
    functionContext = context,
  }
  local reg, regErr = JobWait.registerPhotos(matching, progress)
  if not reg then
    if regErr ~= "canceled" then LrDialogs.message("LR-FrameFlow", regErr, "critical") end
    return
  end

  local job, jobErr = BridgeClient.queueEdit {
    schema_version = "bridge-edit-v1",
    profile_id = profile.profile_id,
    lr_catalog_uuids = reg.uuids,
  }
  if not job then
    LrDialogs.message("LR-FrameFlow", jobErr, "critical")
    return
  end
  Log.info("edit job %s queued with %d photos", job.job_id, #reg.uuids)

  local final, waitErr = JobWait.waitForJob(job.job_id, progress, "Editing")
  if not final then
    progress:done()
    if waitErr == "canceled" then
      LrDialogs.message("Stopped waiting",
        "The Bridge finishes the job, but the results are not applied. Run \"Apply profile\" again later.",
        "info")
    else
      LrDialogs.message("LR-FrameFlow", waitErr, "critical")
    end
    return
  end
  if final.status ~= "completed" then
    progress:done()
    LrDialogs.message("Editing failed", final.last_error or "No reason given.", "critical")
    return
  end

  progress:setCaption("Writing develop settings")
  local applied = 0
  catalog:withWriteAccessDo("LR-FrameFlow: " .. profile.name, function()
    for _, result in ipairs(final.results or {}) do
      local photo = reg.photosByUuid[result.lr_catalog_uuid]
      if photo and type(result.lr_settings) == "table" then
        photo:applyDevelopSettings(PhotoData.prepareSettings(result.lr_settings))
        applied = applied + 1
      end
    end
  end, { timeout = 60 })
  progress:done()
  Log.info("edit job %s: applied %d of %d", job.job_id, applied, #reg.uuids)

  local notes = {}
  if applied < #reg.uuids then
    notes[#notes + 1] = string.format("%d photos got no result (no usable preview).", #reg.uuids - applied)
  end
  if wrongType > 0 then
    notes[#notes + 1] = string.format("%d photos were skipped because they are not %s.",
      wrongType, FORMAT_TEXT[profile.format_type])
  end
  LrDialogs.message(string.format("\"%s\" applied to %d photos", profile.name, applied),
    #notes > 0 and table.concat(notes, "\n") or "Use Edit > Undo to revert.", "info")
end)
