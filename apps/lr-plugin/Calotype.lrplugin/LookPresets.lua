--[[ A look from the photographer's own Lightroom develop presets.

The chosen preset's settings go to the server as `base_preset`; the style layer there
(calotype_edit_serializer.style) takes only its look (tone curve, HSL, color grading, grain,
glow …) and keeps exposure and white balance predicted per photo. The preset itself stays in
Lightroom — nothing of it is stored in the project. Call only from an async task. ]]

local LrApplication = import "LrApplication"
local LrTasks = import "LrTasks"

local LookPresets = {}

-- Our retouch presets only add masks; they are no look.
local SKIP_FOLDERS = { ["Calotype Retouch"] = true }

local function folderName(folder)
  local ok, name = LrTasks.pcall(function() return folder:getName() end)
  return ok and name or ""
end

--- Popup items { title = "Folder / Preset", value = uuid }, sorted, every installed preset.
function LookPresets.items()
  local items = {}
  for _, folder in ipairs(LrApplication.developPresetFolders()) do
    local group = folderName(folder)
    if not SKIP_FOLDERS[group] then
      for _, preset in ipairs(folder:getDevelopPresets()) do
        local ok, uuid, name = LrTasks.pcall(function() return preset:getUuid(), preset:getName() end)
        if ok and uuid then
          items[#items + 1] = { title = group ~= "" and (group .. " / " .. tostring(name)) or tostring(name), value = uuid }
        end
      end
    end
  end
  table.sort(items, function(a, b) return a.title:lower() < b.title:lower() end)
  return items
end

local function find(id)
  for _, folder in ipairs(LrApplication.developPresetFolders()) do
    for _, preset in ipairs(folder:getDevelopPresets()) do
      local ok, uuid, name = LrTasks.pcall(function() return preset:getUuid(), preset:getName() end)
      if ok and (uuid == id or name == id) then return preset, name end
    end
  end
  return nil
end

local function isNumberList(t)
  if #t == 0 then return false end
  for k, v in pairs(t) do
    if type(k) ~= "number" or type(v) ~= "number" then return false end
  end
  return true
end

--- The develop settings of the preset with this uuid (or name) as plain values: numbers,
-- strings, booleans and number lists (tone curves). Masks and other nested tables are left
-- out — they belong to the photo the preset was made on. Returns settings, name or nil.
function LookPresets.settings(id)
  if id == nil or id == "" then return nil end
  local preset, name = find(id)
  if not preset then return nil end
  local ok, settings = LrTasks.pcall(function() return preset:getSetting() end)
  if not ok or type(settings) ~= "table" then return nil end
  local out, n = {}, 0
  for k, v in pairs(settings) do
    local t = type(v)
    if k == "CameraProfile" and v == "Default Profile" then
      -- Lightroom's placeholder for "the preset names no profile": not a look setting.
      -- Passing it on replaced the photographer's camera profile on every photo.
    elseif type(k) == "string" and (t == "number" or t == "string" or t == "boolean") then
      out[k], n = v, n + 1
    elseif type(k) == "string" and t == "table" and isNumberList(v) then
      local copy = {}
      for i, x in ipairs(v) do copy[i] = x end
      out[k], n = copy, n + 1
    end
  end
  if n == 0 then return nil end
  return out, name
end

-- The sliders a profile learns (Lightroom keys), see calotype_edit_serializer.sliders.
local SLIDER_KEYS = { "Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012",
  "Blacks2012", "Vibrance", "Saturation", "Temperature", "Tint", "IncrementalTemperature", "IncrementalTint" }

--- Placeholders of an import preset: the slider values it leaves on every photo it is applied
-- to (Lightroom key -> value), e.g. { Highlights2012 = -100 }. A photo still holding one did
-- not decide that slider, so it does not teach it (train request `untouched`). Values at
-- Lightroom's neutral 0 are left out: they are no trace of the preset. Returns nil when the
-- preset sets no slider.
function LookPresets.placeholders(id)
  local settings = LookPresets.settings(id)
  if not settings then return nil end
  local out, n = {}, 0
  for _, key in ipairs(SLIDER_KEYS) do
    local v = settings[key]
    if type(v) == "number" and v ~= 0 then out[key], n = v, n + 1 end
  end
  if n == 0 then return nil end
  return out
end

return LookPresets
