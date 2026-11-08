--[[ Train and apply without any dialogs.

Used by the menu actions (TrainProfile.lua, ApplyProfile.lua) and by the automation channel
(Automation.lua), so automated end-to-end tests run exactly the code a user triggers.
Every function returns a result table; dialogs are the caller's business.
Call only from an async task. ]]

local BridgeClient = require "BridgeClient"
local JobWait = require "JobWait"
local Log = require "Log"
local PhotoData = require "PhotoData"

local Actions = {}

Actions.MIN_TRAIN_PHOTOS = 3

local function formatText(formatType)
  if formatType == "raw" then return "RAW" end
  return LOC "$$$/LRFrameFlow/Format/Raster=JPEG/TIFF"
end

local function result(ok, title, text, level, extra)
  local r = extra or {}
  r.ok, r.title, r.text, r.level = ok, title, text, level or (ok and "info" or "critical")
  return r
end

--- Ready profiles from the server, sorted by name (for the menu and for automation).
function Actions.readyProfiles()
  local profiles, err = BridgeClient.profiles()
  if not profiles then return nil, err end
  local items = {}
  for _, p in ipairs(profiles) do
    if p.status == "ready" then
      items[#items + 1] = {
        title = string.format("%s  (%s, %s, v%s)", p.name, p.genre, formatText(p.format_type), tostring(p.version)),
        value = p.profile_id,
        profile = p,
      }
    end
  end
  table.sort(items, function(a, b) return a.title:lower() < b.title:lower() end)
  return items
end

--- Train a profile from `photos` (their current develop settings are the target).
-- choice = { name, genre, colorType }.
function Actions.train(photos, choice, progress)
  local reg, regErr = JobWait.registerPhotos(photos, progress)
  if not reg then
    if regErr == "canceled" then return result(false, "LR-FrameFlow", regErr, "info", { canceled = true }) end
    return result(false, "LR-FrameFlow", regErr)
  end
  if reg.formats.raw and reg.formats.jpeg_tiff then
    return result(false, LOC "$$$/LRFrameFlow/Train/MixedTitle=Mixed file types",
      LOC "$$$/LRFrameFlow/Train/Mixed=Please train RAW photos and JPEG/TIFF photos as separate profiles.", "warning")
  end
  if #reg.uuids < Actions.MIN_TRAIN_PHOTOS then
    return result(false, LOC "$$$/LRFrameFlow/Train/NotEnoughTitle=Not enough usable photos",
      LOC("$$$/LRFrameFlow/Train/NotEnough=^1 of the selected photos can be used (videos and other files are skipped).",
        #reg.uuids), "warning")
  end

  local job, jobErr = BridgeClient.queueTrain {
    schema_version = "bridge-train-v1",
    profile_name = choice.name,
    genre = choice.genre,
    format_type = reg.formats.raw and "raw" or "jpeg_tiff",
    color_type = choice.colorType,
    lr_catalog_uuids = reg.uuids,
  }
  if not job then return result(false, "LR-FrameFlow", jobErr) end
  Log.info("train job %s queued with %d photos", job.job_id, #reg.uuids)

  local final, waitErr = JobWait.waitForJob(job.job_id, progress, LOC "$$$/LRFrameFlow/Train/Label=Training")
  if not final then
    if waitErr == "canceled" then
      return result(false, LOC "$$$/LRFrameFlow/Train/BackgroundTitle=Training continues in the background",
        LOC "$$$/LRFrameFlow/Train/Background=The Bridge keeps working on it. The profile appears in \"Apply profile\" once it is ready.",
        "info", { canceled = true, job_id = job.job_id })
    end
    return result(false, "LR-FrameFlow", waitErr, nil, { job_id = job.job_id })
  end
  if final.status ~= "completed" then
    return result(false, LOC "$$$/LRFrameFlow/Train/FailedTitle=Training failed",
      final.last_error or LOC "$$$/LRFrameFlow/Common/NoReason=No reason given.", nil, { job_id = job.job_id })
  end
  return result(true, LOC("$$$/LRFrameFlow/Train/ReadyTitle=Profile \"^1\" is ready", choice.name),
    LOC "$$$/LRFrameFlow/Train/Ready=Select photos and use \"Apply profile to selected photos...\".", "info",
    { job_id = job.job_id, profile_id = final.profile_id, photos = #reg.uuids })
end

--- Apply `profile` (a ready profile from Actions.readyProfiles) to `photos`.
-- Crop keys a straighten result may carry. A photo the photographer has already cropped or
-- straightened keeps its own crop.
local CROP_KEYS = { "CropAngle", "CropLeft", "CropTop", "CropRight", "CropBottom", "HasCrop" }

local function hasOwnCrop(photo)
  local s = photo:getDevelopSettings() or {}
  local angle = tonumber(s.CropAngle) or 0
  local full = (tonumber(s.CropLeft) or 0) == 0 and (tonumber(s.CropTop) or 0) == 0
    and (tonumber(s.CropRight) or 1) == 1 and (tonumber(s.CropBottom) or 1) == 1
  return angle ~= 0 or not full
end

--- Apply `profile` to `photos`. options.straighten: also level photos with clear lines.
function Actions.apply(catalog, photos, profile, progress, options)
  options = options or {}
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
    return result(false, LOC "$$$/LRFrameFlow/Apply/NoMatchTitle=No matching photos",
      LOC("$$$/LRFrameFlow/Apply/NoMatch=\"^1\" is a ^2 profile; none of the selected photos is ^2.",
        profile.name, formatText(profile.format_type)), "warning")
  end

  local reg, regErr = JobWait.registerPhotos(matching, progress)
  if not reg then
    if regErr == "canceled" then return result(false, "LR-FrameFlow", regErr, "info", { canceled = true }) end
    return result(false, "LR-FrameFlow", regErr)
  end

  local job, jobErr = BridgeClient.queueEdit {
    schema_version = "bridge-edit-v1",
    profile_id = profile.profile_id,
    lr_catalog_uuids = reg.uuids,
    straighten = options.straighten or nil,   -- only sent when asked (older Bridges)
  }
  if not job then return result(false, "LR-FrameFlow", jobErr) end
  Log.info("edit job %s queued with %d photos", job.job_id, #reg.uuids)

  local final, waitErr = JobWait.waitForJob(job.job_id, progress, LOC "$$$/LRFrameFlow/Apply/Label=Editing")
  if not final then
    if waitErr == "canceled" then
      return result(false, LOC "$$$/LRFrameFlow/Apply/StoppedTitle=Stopped waiting",
        LOC "$$$/LRFrameFlow/Apply/Stopped=The Bridge finishes the job, but the results are not applied. Run \"Apply profile\" again later.",
        "info", { canceled = true, job_id = job.job_id })
    end
    return result(false, "LR-FrameFlow", waitErr, nil, { job_id = job.job_id })
  end
  if final.status ~= "completed" then
    return result(false, LOC "$$$/LRFrameFlow/Apply/FailedTitle=Editing failed",
      final.last_error or LOC "$$$/LRFrameFlow/Common/NoReason=No reason given.", nil, { job_id = job.job_id })
  end

  progress:setCaption(LOC "$$$/LRFrameFlow/Apply/Writing=Writing develop settings")
  local applied, appliedUuids, straightened, keptCrop = 0, {}, 0, 0
  catalog:withWriteAccessDo(LOC("$$$/LRFrameFlow/Apply/Undo=LR-FrameFlow: ^1", profile.name), function()
    for _, r in ipairs(final.results or {}) do
      local photo = reg.photosByUuid[r.lr_catalog_uuid]
      if photo and type(r.lr_settings) == "table" then
        local settings = r.lr_settings
        if settings.CropAngle ~= nil then
          if hasOwnCrop(photo) then
            for _, k in ipairs(CROP_KEYS) do settings[k] = nil end
            keptCrop = keptCrop + 1
          else
            straightened = straightened + 1
          end
        end
        photo:applyDevelopSettings(PhotoData.prepareSettings(settings))
        applied = applied + 1
        appliedUuids[#appliedUuids + 1] = r.lr_catalog_uuid
      end
    end
  end, { timeout = 60 })
  Log.info("edit job %s: applied %d of %d", job.job_id, applied, #reg.uuids)

  local notes = {}
  if applied < #reg.uuids then
    notes[#notes + 1] = LOC("$$$/LRFrameFlow/Apply/NoResult=^1 photos got no result (no usable preview).", #reg.uuids - applied)
  end
  if straightened > 0 then
    notes[#notes + 1] = LOC("$$$/LRFrameFlow/Apply/Straightened=^1 photos were straightened.", straightened)
  end
  if keptCrop > 0 then
    notes[#notes + 1] = LOC("$$$/LRFrameFlow/Apply/KeptCrop=^1 photos kept their own crop.", keptCrop)
  end
  if wrongType > 0 then
    notes[#notes + 1] = LOC("$$$/LRFrameFlow/Apply/WrongType=^1 photos were skipped because they are not ^2.",
      wrongType, formatText(profile.format_type))
  end
  return result(true, LOC("$$$/LRFrameFlow/Apply/DoneTitle=\"^1\" applied to ^2 photos", profile.name, applied),
    #notes > 0 and table.concat(notes, "\n") or LOC "$$$/LRFrameFlow/Apply/UndoHint=Use Edit > Undo to revert.", "info",
    { job_id = job.job_id, applied = applied, applied_uuids = appliedUuids, skipped_type = wrongType,
      straightened = straightened, kept_crop = keptCrop })
end

-- ---------------------------------------------------------------------------- culling

local BUCKETS = {
  { key = "keep", title = LOC "$$$/LRFrameFlow/Cull/Keep=1 Keep" },
  { key = "uncertain", title = LOC "$$$/LRFrameFlow/Cull/Uncertain=2 Check" },
  { key = "reject", title = LOC "$$$/LRFrameFlow/Cull/Reject=3 Sort out" },
}
Actions.CULL_PARENT = "LR-FrameFlow"


--- Sort `photos` into keep / check / sort out. Photos that already have stars or a pick/reject
-- flag teach the scorer. The result goes into collections in the set "LR-FrameFlow > <name>";
-- stars, flags and labels stay untouched. options.set_name overrides the set name.
function Actions.cull(catalog, photos, progress, options)
  options = options or {}
  -- Series (near-identical shots) are found in shooting order. Read the times first: catalog
  -- calls yield, and yielding inside table.sort's comparator is an error in Lightroom.
  local meta = catalog:batchGetRawMetadata(photos, { "dateTimeOriginal", "dateTime" })
  local when, ordered = {}, {}
  for i, p in ipairs(photos) do
    local m = meta[p] or {}
    when[p] = m.dateTimeOriginal or m.dateTime or 0
    ordered[i] = p
  end
  table.sort(ordered, function(a, b) return when[a] < when[b] end)

  local reg, regErr = JobWait.registerPhotos(ordered, progress)
  if not reg then
    if regErr == "canceled" then return result(false, "LR-FrameFlow", regErr, "info", { canceled = true }) end
    return result(false, "LR-FrameFlow", regErr)
  end
  local job, jobErr = BridgeClient.queueCull { schema_version = "bridge-cull-v1", lr_catalog_uuids = reg.uuids }
  if not job then return result(false, "LR-FrameFlow", jobErr) end
  Log.info("cull job %s queued with %d photos", job.job_id, #reg.uuids)

  local final, waitErr = JobWait.waitForJob(job.job_id, progress, LOC "$$$/LRFrameFlow/Cull/Label=Sorting")
  if not final then
    if waitErr == "canceled" then
      return result(false, LOC "$$$/LRFrameFlow/Apply/StoppedTitle=Stopped waiting",
        LOC "$$$/LRFrameFlow/Cull/Stopped=The Bridge finishes the job, but no collections were made. Run it again later.",
        "info", { canceled = true, job_id = job.job_id })
    end
    return result(false, "LR-FrameFlow", waitErr, nil, { job_id = job.job_id })
  end
  if final.status ~= "completed" then
    return result(false, LOC "$$$/LRFrameFlow/Cull/FailedTitle=Sorting failed",
      final.last_error or LOC "$$$/LRFrameFlow/Common/NoReason=No reason given.", nil, { job_id = job.job_id })
  end

  local byBucket, counts, method, decisions = { keep = {}, uncertain = {}, reject = {} }, {}, "rules", {}
  for _, r in ipairs(final.results or {}) do
    local photo = reg.photosByUuid[r.lr_catalog_uuid]
    if photo and byBucket[r.bucket] then
      local list = byBucket[r.bucket]
      list[#list + 1] = photo
      method = r.method or method
      decisions[#decisions + 1] = { uuid = r.lr_catalog_uuid, bucket = r.bucket, reason = r.reason }
    end
  end
  local setName = options.set_name or LOC("$$$/LRFrameFlow/Cull/SetName=Culling ^1", os.date("%Y-%m-%d %H:%M"))
  progress:setCaption(LOC "$$$/LRFrameFlow/Cull/Writing=Creating collections")
  catalog:withWriteAccessDo(LOC "$$$/LRFrameFlow/Cull/Undo=LR-FrameFlow: culling", function()
    local parent = catalog:createCollectionSet(Actions.CULL_PARENT, nil, true)
    local set = catalog:createCollectionSet(setName, parent, true)
    for _, b in ipairs(BUCKETS) do
      local collection = catalog:createCollection(b.title, set, true)
      collection:removeAllPhotos()
      if #byBucket[b.key] > 0 then collection:addPhotos(byBucket[b.key]) end
      counts[b.key] = #byBucket[b.key]
    end
  end, { timeout = 60 })
  Log.info("cull job %s: keep %d, check %d, sort out %d (%s)", job.job_id, counts.keep, counts.uncertain,
    counts.reject, method)

  local how = method == "learned"
    and LOC "$$$/LRFrameFlow/Cull/Learned=Learned from the photos you had already rated or flagged."
    or LOC "$$$/LRFrameFlow/Cull/Rules=Starter rules — rate or flag about 10 keepers and 10 rejects among the selected photos, and LR-FrameFlow learns your taste."
  return result(true, LOC("$$$/LRFrameFlow/Cull/DoneTitle=^1 photos sorted", counts.keep + counts.uncertain + counts.reject),
    LOC("$$$/LRFrameFlow/Cull/Done=Keep ^1, check ^2, sort out ^3.^nCollections: LR-FrameFlow > ^4^n^5",
      counts.keep, counts.uncertain, counts.reject, setName, how), "info",
    { job_id = job.job_id, counts = counts, method = method, set_name = setName, decisions = decisions })
end

return Actions
