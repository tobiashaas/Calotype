--[[ Commands of the automation channel (end-to-end tests in a real Lightroom).

A fixed set of commands — nothing from a command is ever executed as code. `apply` and
`train` call the same Actions the menu items use. Every handler gets the catalog and the
command's args and returns a JSON-serializable table. Call only from an async task. ]]

local LrApplication = import "LrApplication"
local LrApplicationView = import "LrApplicationView"
local LrDevelopController = import "LrDevelopController"
local LrProgressScope = import "LrProgressScope"
local LrTasks = import "LrTasks"

local Actions = require "Actions"
local Json = require "Json"
local PhotoData = require "PhotoData"

local Commands = {}

-- Catalog calls yield, and Lua 5.1's pcall cannot yield ("Yielding is not allowed within a C
-- or metamethod call", found in the first automated run). LrTasks.pcall can.
local pcall = LrTasks.pcall or pcall

local PLUGIN_VERSION = "0.3.0"
local LIST_KEYS = { "uuid", "path", "fileFormat", "rating", "pickStatus", "isVirtualCopy" }

local function photosByUuid(catalog, uuids)
  local photos, missing = {}, {}
  for _, uuid in ipairs(uuids or {}) do
    local photo = catalog:findPhotoByUuid(uuid)
    if photo then photos[#photos + 1] = photo else missing[#missing + 1] = uuid end
  end
  return photos, missing
end

local function progressScope(title)
  return LrProgressScope { title = "Calotype (automation): " .. title }
end

-- Result tables of Actions contain only plain values; copy what a test needs.
local function plain(r)
  return Json.object({
    ok = r.ok, title = r.title, text = r.text, canceled = r.canceled, job_id = r.job_id,
    profile_id = r.profile_id, applied = r.applied, applied_uuids = r.applied_uuids,
    skipped_type = r.skipped_type, photos = r.photos, straightened = r.straightened,
    kept_crop = r.kept_crop, masks = r.masks,
  })
end

function Commands.ping(catalog)
  return Json.object({
    plugin = PLUGIN_VERSION,
    lightroom = LrApplication.versionString and LrApplication.versionString() or nil,
    catalog = catalog:getPath(),
    photos = #catalog:getAllPhotos(),
    -- "de" when Lightroom runs in German (TranslatedStrings_de.txt), "en" otherwise
    language = LOC "$$$/Calotype/Language=en",
  })
end

function Commands.list_photos(catalog, args)
  local all = catalog:getAllPhotos()
  local offset, limit = tonumber(args.offset) or 0, tonumber(args.limit) or 50
  local slice = {}
  for i = offset + 1, math.min(#all, offset + limit) do slice[#slice + 1] = all[i] end
  local meta = catalog:batchGetRawMetadata(slice, LIST_KEYS)
  local out = {}
  for _, photo in ipairs(slice) do
    local m = meta[photo] or {}
    local format = PhotoData.formatType(m.fileFormat)
    if not args.format or args.format == format then
      out[#out + 1] = Json.object({
        uuid = m.uuid, path = m.path, file_format = m.fileFormat, format_type = format,
        rating = m.rating, pick_status = m.pickStatus, virtual_copy = m.isVirtualCopy,
      })
    end
  end
  return Json.object({ total = #all, photos = out })
end

function Commands.develop_settings(catalog, args)
  local photos, missing = photosByUuid(catalog, args.uuids)
  local wanted = args.keys
  local out = Json.object({})
  for _, photo in ipairs(photos) do
    local settings = photo:getDevelopSettings() or {}
    local picked = Json.object({})
    if wanted then
      for _, k in ipairs(wanted) do picked[k] = settings[k] end
    else
      picked = Json.object(settings)
    end
    out[photo:getRawMetadata("uuid")] = picked
  end
  return Json.object({ settings = out, missing = missing })
end

function Commands.set_develop_settings(catalog, args)
  local count = 0
  catalog:withWriteAccessDo("Calotype automation: restore settings", function()
    for uuid, settings in pairs(args.settings or {}) do
      local photo = catalog:findPhotoByUuid(uuid)
      if photo and type(settings) == "table" then
        photo:applyDevelopSettings(PhotoData.prepareSettings(settings))
        count = count + 1
      end
    end
  end, { timeout = 60 })
  return Json.object({ updated = count })
end

function Commands.select(catalog, args)
  local photos = photosByUuid(catalog, args.uuids)
  if #photos > 0 then catalog:setSelectedPhotos(photos[1], photos) end
  return Json.object({ selected = #photos })
end

-- Lightroom's own crop for a straighten angle: Develop computes the largest crop that keeps the
-- aspect ratio inside the rotated photo. Read it, then put the photo back as it was. Used to
-- check our crop formula against Lightroom (tools/lr_e2e).
local CROP_KEYS = { "CropAngle", "CropLeft", "CropTop", "CropRight", "CropBottom", "HasCrop",
  "CropConstrainToWarp", "orientation" }

function Commands.straighten_probe(catalog, args)
  local photo = catalog:findPhotoByUuid(args.uuid)
  if not photo then error("no photo " .. tostring(args.uuid)) end
  local before = photo:getDevelopSettings()
  catalog:setSelectedPhotos(photo, { photo })
  LrApplicationView.switchToModule("develop")
  LrTasks.sleep(1.5)
  local out = Json.object({ results = {} })
  LrDevelopController.selectTool("crop")
  LrTasks.sleep(0.8)
  for _, angle in ipairs(args.angles or { args.angle or 0 }) do
    LrDevelopController.setValue("straightenAngle", angle)
    LrTasks.sleep(1.0)
    local s = photo:getDevelopSettings()
    local r = Json.object({ angle = angle, controller = LrDevelopController.getValue("straightenAngle") })
    for _, k in ipairs(CROP_KEYS) do r[k] = s[k] end
    out.results[#out.results + 1] = r
  end
  LrDevelopController.selectTool("loupe")
  LrTasks.sleep(0.5)
  out.dimensions = photo:getRawMetadata("croppedDimensions")
  out.orientation = photo:getRawMetadata("orientation")
  local restore = {}
  for _, k in ipairs(CROP_KEYS) do
    if k ~= "orientation" and before[k] ~= nil then restore[k] = before[k] end
  end
  catalog:withWriteAccessDo("Calotype automation: restore crop", function()
    photo:applyDevelopSettings(restore)
  end, { timeout = 30 })
  local after = photo:getDevelopSettings()
  out.restored = after.CropAngle == before.CropAngle and after.CropLeft == before.CropLeft
    and after.CropRight == before.CropRight and after.CropTop == before.CropTop
    and after.CropBottom == before.CropBottom
  return out
end

function Commands.apply(catalog, args)
  local items, err = Actions.readyProfiles()
  if not items then error(err) end
  local profile
  for _, item in ipairs(items) do
    if item.profile.profile_id == args.profile or item.profile.name == args.profile then
      profile = item.profile
    end
  end
  local photos, missing = photosByUuid(catalog, args.uuids)
  -- No profile + learn_from_edits: the look of the selection's edited photos only.
  if args.profile == nil and args.learn_from_edits == true then profile = Actions.ownEditsProfile(photos) end
  if not profile then error("no ready profile " .. tostring(args.profile)) end
  local progress = progressScope(profile.name)
  local ok, r = pcall(Actions.apply, catalog, photos, profile, progress,
    { straighten = args.straighten == true, retouch = args.retouch,
      learnFromEdits = args.learn_from_edits == true })
  progress:done()
  if not ok then error(r) end
  local out = plain(r)
  out.missing = missing
  return out
end

function Commands.train(catalog, args)
  local photos, missing = photosByUuid(catalog, args.uuids)
  local choice = { name = args.name, genre = args.genre or "other", colorType = args.color_type or "color" }
  local progress = progressScope(tostring(choice.name))
  local ok, r = pcall(Actions.train, photos, choice, progress)
  progress:done()
  if not ok then error(r) end
  local out = plain(r)
  out.missing = missing
  return out
end

function Commands.cull(catalog, args)
  local photos, missing = photosByUuid(catalog, args.uuids)
  local progress = progressScope("culling")
  local ok, r = pcall(Actions.cull, catalog, photos, progress, { set_name = args.set_name })
  progress:done()
  if not ok then error(r) end
  return Json.object({ ok = r.ok, title = r.title, text = r.text, counts = r.counts, method = r.method,
    set_name = r.set_name, decisions = r.decisions, missing = missing })
end

-- Our retouch corrections, also from before the rename (ADR 006).
local function ours(group)
  local name = tostring(group.CorrectionName or "")
  return name:find("^Calotype ") ~= nil or name:find("^Tarsier ") ~= nil or name:find("^LR%-FrameFlow ") ~= nil
end

--- Our retouch masks and Calotype snapshots of photos, for checks and test cleanup.
function Commands.retouch_state(catalog, args)
  local photos = photosByUuid(catalog, args.uuids)
  local out = Json.object({})
  for _, photo in ipairs(photos) do
    local groups = (photo:getDevelopSettings() or {}).MaskGroupBasedCorrections or {}
    local found = {}
    for _, g in ipairs(groups) do
      if ours(g) then
        local digests, errors = 0, 0
        for _, m in ipairs(g.CorrectionMasks or {}) do
          if m.MaskDigest then digests = digests + 1 end
          if (tonumber(m.ErrorReason or 0) or 0) ~= 0 then errors = errors + 1 end
        end
        found[#found + 1] = Json.object({ name = g.CorrectionName, masks = #(g.CorrectionMasks or {}),
          computed = digests, nothing_found = errors })
      end
    end
    local snaps = {}
    local ok, list = pcall(function() return photo:getDevelopSnapshots() end)
    for _, s in ipairs(ok and list or {}) do snaps[#snaps + 1] = s.name end
    out[photo:getRawMetadata("uuid")] = Json.object({ masks = found, all_masks = #groups, snapshots = snaps })
  end
  return out
end

--- Test cleanup: remove our masks (others stay) and our snapshots from these photos.
function Commands.remove_retouch(catalog, args)
  local photos = photosByUuid(catalog, args.uuids)
  local Retouch = require "Retouch"
  local removed = 0
  catalog:withWriteAccessDo("Calotype automation: remove retouch", function()
    for _, photo in ipairs(photos) do
      local groups = (photo:getDevelopSettings() or {}).MaskGroupBasedCorrections or {}
      local keep = {}
      for _, g in ipairs(groups) do
        if ours(g) then removed = removed + 1 else keep[#keep + 1] = g end
      end
      if #keep ~= #groups then photo:applyDevelopSettings({ MaskGroupBasedCorrections = keep }) end
    end
  end, { timeout = 60 })
  for _, photo in ipairs(photos) do
    local ok, list = pcall(function() return photo:getDevelopSnapshots() end)
    for _, s in ipairs(ok and list or {}) do
      if s.name == Retouch.SNAPSHOT and photo.deleteDevelopSnapshot then
        pcall(function() photo:deleteDevelopSnapshot(s.snapshotID) end)
      end
    end
  end
  return Json.object({ removed = removed })
end

-- Our subject correction on a photo: its values and whether Lightroom computed the mask.
local function subjectState(photo)
  for _, g in ipairs((photo:getDevelopSettings() or {}).MaskGroupBasedCorrections or {}) do
    if ours(g) then
      local computed = 0
      for _, m in ipairs(g.CorrectionMasks or {}) do
        if m.MaskDigest then computed = computed + 1 end
      end
      return Json.object({ name = g.CorrectionName, exposure = g.LocalExposure2012,
        shadows = g.LocalShadows2012, masks = #(g.CorrectionMasks or {}), computed = computed })
    end
  end
  return Json.object({ none = true })
end

local function removeOurs(catalog, photo)
  catalog:withWriteAccessDo("Calotype automation: mask probe cleanup", function()
    local groups = (photo:getDevelopSettings() or {}).MaskGroupBasedCorrections or {}
    local keep = {}
    for _, g in ipairs(groups) do if not ours(g) then keep[#keep + 1] = g end end
    photo:applyDevelopSettings({ MaskGroupBasedCorrections = keep })
  end, { timeout = 30 })
end

--- Probe (test only): can a plugin set its own strength on an AI mask? On one photo our
-- installed subject preset (the retouch path) is applied and computed, then only its correction
-- values are changed with applyDevelopSettings. Every step is logged (a hang shows where); our
-- mask is removed again afterwards, the photographer's own masks stay.
-- Verified in Lightroom 16.0: the values arrive and the mask stays computed. Not this way: a
-- preset made at runtime (LrApplication.addDevelopPresetForPlugin) holding only the mask also
-- set the photo's white balance to 1500 K / -150 when applied.
function Commands.mask_probe(catalog, args)
  local Log = require "Log"
  local Retouch = require "Retouch"
  local photo = catalog:findPhotoByUuid(args.uuid or "")
  if not photo then error("unknown photo " .. tostring(args.uuid)) end
  local out = Json.object({ steps = {} })
  local function step(name, fn)
    Log.info("mask_probe: %s ...", name)
    local ok, err = pcall(fn)
    local state = subjectState(photo)
    Log.info("mask_probe: %s ok=%s %s", name, tostring(ok), ok and "" or tostring(err))
    out.steps[#out.steps + 1] = Json.object({ step = name, ok = ok, error = not ok and tostring(err) or nil,
      state = state })
    return ok
  end
  local function compute()
    -- Lightroom may take the preset over a moment after the write transaction.
    for _ = 1, 20 do
      if not subjectState(photo).none then break end
      LrTasks.sleep(0.25)
    end
    if subjectState(photo).none then error("no mask of ours on the photo — nothing to compute") end
    photo:updateAISettings()
  end
  local base = Retouch.findPresets().subject
  if not base then error("subject preset not installed") end

  if step("apply preset", function()
    catalog:withWriteAccessDo("Calotype automation: mask probe", function()
      photo:applyDevelopPreset(base, _PLUGIN)
    end, { timeout = 30 })
  end) then
    step("compute mask", compute)
    step("change values", function()
      catalog:withWriteAccessDo("Calotype automation: mask probe values", function()
        local groups = (photo:getDevelopSettings() or {}).MaskGroupBasedCorrections or {}
        for _, g in ipairs(groups) do
          if ours(g) then g.LocalExposure2012, g.LocalShadows2012 = 0.22, 0.44 end
        end
        photo:applyDevelopSettings({ MaskGroupBasedCorrections = groups })
      end, { timeout = 30 })
    end)
  end
  step("cleanup", function() removeOurs(catalog, photo) end)
  return out
end

--- Give photos our AI masks with set strengths (test setup for learned mask strengths):
-- args.uuids, args.strengths = {subject = {LocalShadows2012 = 0.25, …}}. The same steps as an
-- apply with learned strengths: preset, detection, then the values.
function Commands.set_mask_strength(catalog, args)
  local Retouch = require "Retouch"
  local photos = photosByUuid(catalog, args.uuids)
  local presets = Retouch.findPresets()
  local ids = Retouch.idsFor({}, args.strengths)
  catalog:withWriteAccessDo("Calotype automation: prepare masks", function()
    for _, photo in ipairs(photos) do Retouch.prepare(photo) end
  end, { timeout = 60 })
  local added = 0
  catalog:withWriteAccessDo("Calotype automation: add masks", function()
    for _, photo in ipairs(photos) do added = added + Retouch.apply(photo, presets, ids) end
  end, { timeout = 60 })
  local found, removed = Retouch.finish(catalog, photos)
  local set = 0
  catalog:withWriteAccessDo("Calotype automation: mask strengths", function()
    for _, photo in ipairs(photos) do set = set + Retouch.setStrengths(photo, args.strengths) end
  end, { timeout = 60 })
  return Json.object({ added = added, found = found, removed = removed, set = set })
end

--- Remove a culling collection set made by Commands.cull (test cleanup). Only sets directly
-- inside "Calotype" whose name is given exactly; photos themselves are never touched.
function Commands.remove_cull_set(catalog, args)
  local removed = 0
  catalog:withWriteAccessDo("Calotype automation: remove culling set", function()
    for _, parent in ipairs(catalog:getChildCollectionSets()) do
      if parent:getName() == Actions.CULL_PARENT then
        for _, set in ipairs(parent:getChildCollectionSets()) do
          if set:getName() == args.set_name then
            set:delete()
            removed = removed + 1
          end
        end
      end
    end
  end, { timeout = 30 })
  return Json.object({ removed = removed })
end

--- Run one command; returns ok, result (result = { error = message } on failure).
function Commands.run(catalog, command)
  local handler = Commands[command.command]
  if type(handler) ~= "function" or command.command == "run" then
    return false, Json.object({ error = "unknown command " .. tostring(command.command) })
  end
  local args = type(command.args) == "table" and command.args or {}
  local ok, result = pcall(handler, catalog, args)
  if not ok then return false, Json.object({ error = tostring(result) }) end
  return true, result
end

return Commands
