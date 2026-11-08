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

local PLUGIN_VERSION = "0.2.0"
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
  return LrProgressScope { title = "LR-FrameFlow (automation): " .. title }
end

-- Result tables of Actions contain only plain values; copy what a test needs.
local function plain(r)
  return Json.object({
    ok = r.ok, title = r.title, text = r.text, canceled = r.canceled, job_id = r.job_id,
    profile_id = r.profile_id, applied = r.applied, applied_uuids = r.applied_uuids,
    skipped_type = r.skipped_type, photos = r.photos, straightened = r.straightened,
    kept_crop = r.kept_crop,
  })
end

function Commands.ping(catalog)
  return Json.object({
    plugin = PLUGIN_VERSION,
    lightroom = LrApplication.versionString and LrApplication.versionString() or nil,
    catalog = catalog:getPath(),
    photos = #catalog:getAllPhotos(),
    -- "de" when Lightroom runs in German (TranslatedStrings_de.txt), "en" otherwise
    language = LOC "$$$/LRFrameFlow/Language=en",
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
  catalog:withWriteAccessDo("LR-FrameFlow automation: restore settings", function()
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
  catalog:withWriteAccessDo("LR-FrameFlow automation: restore crop", function()
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
  if not profile then error("no ready profile " .. tostring(args.profile)) end
  local photos, missing = photosByUuid(catalog, args.uuids)
  local progress = progressScope(profile.name)
  local ok, r = pcall(Actions.apply, catalog, photos, profile, progress, { straighten = args.straighten == true })
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
