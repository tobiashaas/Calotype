--[[ What the Bridge needs per photo: catalog UUID, original file path, develop settings
(the training target) and a small EXIF snapshot. The Bridge builds the preview itself
from the original file, so nothing is exported here. ]]

local Json = require "Json"

local PhotoData = {}

local RAW_FORMATS = { RAW = true, DNG = true }
local RASTER_FORMATS = { JPG = true, TIFF = true, PNG = true, PSD = false, HEIC = true }

--- "raw", "jpeg_tiff" or nil (video and unsupported files).
function PhotoData.formatType(fileFormat)
  if RAW_FORMATS[fileFormat] then return "raw" end
  if RASTER_FORMATS[fileFormat] then return "jpeg_tiff" end
  return nil
end

local function exifSnapshot(photo)
  local function formatted(key)
    local ok, v = pcall(photo.getFormattedMetadata, photo, key)
    if ok and v ~= nil and v ~= "" then return v end
    return nil
  end
  local function raw(key)
    local ok, v = pcall(photo.getRawMetadata, photo, key)
    if ok then return v end
    return nil
  end
  return Json.object({
    camera = formatted("cameraModel"),
    lens = formatted("lens"),
    iso = raw("isoSpeedRating"),
    shutter_speed = raw("shutterSpeed"),
    aperture = raw("aperture"),
    focal_length = raw("focalLength"),
    date_time_original = raw("dateTimeOriginalISO8601"),
  })
end

local PICK_STATUS = { [1] = 1, [0] = 0, [-1] = -1 }

--- The photographer's decisions: culling labels (ADR 005).
function PhotoData.decisions(photo)
  local function raw(key)
    local ok, v = pcall(photo.getRawMetadata, photo, key)
    if ok then return v end
    return nil
  end
  local label = raw("colorNameForLabel")
  if label == "" or label == "none" then label = nil end
  local rating = raw("rating")
  return Json.object({
    rating = type(rating) == "number" and rating or nil,
    pick_status = PICK_STATUS[raw("pickStatus")],
    color_label = label,
  })
end

--- Request body for POST /v1/photos plus the photo's format type.
-- Returns nil, reason for photos the Bridge cannot use.
function PhotoData.collect(photo)
  local fileFormat = photo:getRawMetadata("fileFormat")
  local formatType = PhotoData.formatType(fileFormat)
  if not formatType then
    return nil, "unsupported file type " .. tostring(fileFormat)
  end
  local body = {
    schema_version = "bridge-photo-v1",
    lr_catalog_uuid = photo:getRawMetadata("uuid"),
    file_path = photo:getRawMetadata("path"),
    exif_snapshot = exifSnapshot(photo),
    lr_develop_settings = Json.object(photo:getDevelopSettings() or {}),
    lr_metadata = PhotoData.decisions(photo),
  }
  return body, formatType
end

--- Lightroom needs WhiteBalance = "Custom" for explicit temperature/tint values.
function PhotoData.prepareSettings(settings)
  local out = {}
  for k, v in pairs(settings) do
    if v ~= Json.null then out[k] = v end
  end
  if out.Temperature or out.Tint or out.IncrementalTemperature or out.IncrementalTint then
    out.WhiteBalance = "Custom"
  end
  return out
end

return PhotoData
