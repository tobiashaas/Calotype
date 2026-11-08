--[[ Retouch with Lightroom's own AI masks (subject, background, skin, eyes, teeth, sky).

The masks come from the project's retouch presets (presets/retouch, installed by the Bridge into
Camera Raw's settings folder). A preset only stores the mask *definition*; Lightroom finds the
subject, sky … on each photo with photo:updateAISettings() (Lightroom 13.3+). Masks that find
nothing (no sky indoors, no teeth with a closed mouth) are removed again, so no warnings stay.

Every correction is named "Tarsier <id>": that is how our presets are found (Lightroom gives
presets its own UUIDs) and how a re-apply replaces our earlier masks without touching the
photographer's own. Before the first change a develop snapshot "Tarsier: before" is made,
so the original is one click away. Call only from an async task. ]]

local LrApplication = import "LrApplication"
local LrTasks = import "LrTasks"

local Retouch = {}

Retouch.ITEMS = {
  { id = "subject", title = LOC "$$$/Tarsier/Retouch/Subject=Lift subject" },
  { id = "background", title = LOC "$$$/Tarsier/Retouch/Background=Calm background" },
  { id = "skin", title = LOC "$$$/Tarsier/Retouch/Skin=Soften skin" },
  { id = "eyes", title = LOC "$$$/Tarsier/Retouch/Eyes=Clearer eyes" },
  { id = "teeth", title = LOC "$$$/Tarsier/Retouch/Teeth=Brighten teeth" },
  { id = "sky", title = LOC "$$$/Tarsier/Retouch/Sky=Deepen sky" },
}

local PREFIX = "Tarsier "
local OLD_PREFIX = "LR-FrameFlow "   -- masks from before the rename (ADR 006) count as ours
Retouch.SNAPSHOT = LOC "$$$/Tarsier/Retouch/Snapshot=Tarsier: before"

-- The retouch id of one of our corrections ("Tarsier subject" → "subject"), else nil.
local function ourId(group)
  if type(group) ~= "table" then return nil end
  local name = tostring(group.CorrectionName or "")
  for _, prefix in ipairs({ PREFIX, OLD_PREFIX }) do
    if name:sub(1, #prefix) == prefix then return name:sub(#prefix + 1) end
  end
  return nil
end

local function isOurs(group)
  return ourId(group) ~= nil
end

--- id → installed develop preset, found by the name of the mask correction it adds.
function Retouch.findPresets()
  local found = {}
  for _, folder in ipairs(LrApplication.developPresetFolders()) do
    for _, preset in ipairs(folder:getDevelopPresets()) do
      local ok, settings = LrTasks.pcall(function() return preset:getSetting() end)
      local groups = ok and type(settings) == "table" and settings.MaskGroupBasedCorrections
      if type(groups) == "table" and #groups == 1 and isOurs(groups[1]) then
        local id = ourId(groups[1])
        -- An old preset (before the rename) only fills a gap, the new one wins.
        if not found[id] or groups[1].CorrectionName:sub(1, #PREFIX) == PREFIX then found[id] = preset end
      end
    end
  end
  return found
end

local function hasSnapshot(photo)
  local ok, snaps = LrTasks.pcall(function() return photo:getDevelopSnapshots() end)
  for _, s in ipairs(ok and snaps or {}) do
    if s.name == Retouch.SNAPSHOT then return true end
  end
  return false
end

--- In its own catalog write transaction, before the photo is changed: keep the original as a snapshot
-- (only the first time — a re-apply must not overwrite the true original) and drop our own
-- masks from an earlier run. The photographer's own masks stay.
function Retouch.prepare(photo)
  if photo.createDevelopSnapshot and not hasSnapshot(photo) then
    LrTasks.pcall(function() photo:createDevelopSnapshot(Retouch.SNAPSHOT, false) end)
  end
  local groups = (photo:getDevelopSettings() or {}).MaskGroupBasedCorrections
  if type(groups) ~= "table" then return end
  local keep, removed = {}, 0
  for _, g in ipairs(groups) do
    if isOurs(g) then removed = removed + 1 else keep[#keep + 1] = g end
  end
  if removed > 0 then photo:applyDevelopSettings({ MaskGroupBasedCorrections = keep }) end
end

--- Inside catalog write access: add the chosen masks. Returns how many were added.
function Retouch.apply(photo, presets, ids)
  local added = 0
  for _, id in ipairs(ids) do
    if presets[id] then
      photo:applyDevelopPreset(presets[id], _PLUGIN)
      added = added + 1
    end
  end
  return added
end

-- found / nothing to find / not computed yet, for our corrections on one photo.
local function status(photo)
  local groups = (photo:getDevelopSettings() or {}).MaskGroupBasedCorrections or {}
  local empty, pending, found = {}, 0, 0
  for i, g in ipairs(groups) do
    if isOurs(g) then
      local masks, failed, waiting = g.CorrectionMasks or {}, 0, 0
      for _, m in ipairs(masks) do
        if (tonumber(m.ErrorReason or 0) or 0) ~= 0 then failed = failed + 1
        elseif not m.MaskDigest then waiting = waiting + 1 end
      end
      if #masks > 0 and failed == #masks then empty[i] = true
      elseif waiting > 0 then pending = pending + 1
      else found = found + 1 end
    end
  end
  return groups, empty, pending, found
end

--- After the write transaction: let Lightroom detect the masks, remove the empty ones.
-- Returns found, removed, photos still pending (nil when this Lightroom cannot detect).
function Retouch.finish(catalog, photos, progress)
  if not (photos[1] and photos[1].updateAISettings) then return 0, 0, nil end
  local found, removed, pending = 0, 0, {}
  for i, photo in ipairs(photos) do
    if progress then progress:setPortionComplete(i - 1, #photos) end
    LrTasks.pcall(function() photo:updateAISettings() end)
    local ok, groups, empty, waiting, hits = LrTasks.pcall(status, photo)
    if ok and waiting > 0 then
      LrTasks.sleep(0.5)
      LrTasks.pcall(function() photo:updateAISettings() end)
      ok, groups, empty, waiting, hits = LrTasks.pcall(status, photo)
    end
    if ok then
      found = found + hits
      if next(empty) then
        local keep = {}
        for j, g in ipairs(groups) do
          if empty[j] then removed = removed + 1 else keep[#keep + 1] = g end
        end
        LrTasks.pcall(function()
          catalog:withWriteAccessDo(LOC "$$$/Tarsier/Retouch/Cleanup=Tarsier: remove empty masks", function()
            photo:applyDevelopSettings({ MaskGroupBasedCorrections = keep })
          end, { timeout = 30 })
        end)
      end
    end
    if not ok or waiting > 0 then pending[#pending + 1] = photo end
  end
  return found, removed, pending
end

return Retouch
