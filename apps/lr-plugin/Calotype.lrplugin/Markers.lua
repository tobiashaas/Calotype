--[[ Accepted photos: how the photographer marks photos they reviewed after Calotype applied a
profile and left unchanged.

Every photographer marks differently (one uses green for "uploaded", another colours as
groups), so the marker is theirs to choose and the profile keeps it: none, a colour label, or a
minimum star rating. A photo that still holds Calotype's result is learned only when it carries
the marker — without it the profile would learn from itself. Call only from an async task. ]]

local LrTasks = import "LrTasks"

local pcall = LrTasks.pcall or pcall

local Markers = {}

local COLORS = { "red", "yellow", "green", "blue", "purple" }

local COLOR_TITLES = {
  red = LOC "$$$/Calotype/Marker/Red=Red label",
  yellow = LOC "$$$/Calotype/Marker/Yellow=Yellow label",
  green = LOC "$$$/Calotype/Marker/Green=Green label",
  blue = LOC "$$$/Calotype/Marker/Blue=Blue label",
  purple = LOC "$$$/Calotype/Marker/Purple=Purple label",
}

--- Popup items; values are "none", "label:<colour>" or "rating:<n>".
function Markers.items()
  local items = { { title = LOC "$$$/Calotype/Marker/None=No marker", value = "none" } }
  for _, color in ipairs(COLORS) do
    items[#items + 1] = { title = COLOR_TITLES[color], value = "label:" .. color }
  end
  for n = 1, 5 do
    items[#items + 1] = { title = LOC("$$$/Calotype/Marker/Rating=At least ^1 stars", n), value = "rating:" .. n }
  end
  return items
end

--- Popup value -> the marker the server keeps ({ kind = "none" } / label / rating).
function Markers.fromValue(value)
  local color = type(value) == "string" and value:match("^label:(%a+)$")
  if color then return { kind = "label", value = color } end
  local n = type(value) == "string" and tonumber(value:match("^rating:(%d)$"))
  if n then return { kind = "rating", min = n } end
  return { kind = "none" }
end

--- The profile's marker (as the server lists it, may be nil) -> popup value.
function Markers.toValue(marker)
  if type(marker) ~= "table" then return "none" end
  if marker.kind == "label" and type(marker.value) == "string" then return "label:" .. marker.value end
  if marker.kind == "rating" and tonumber(marker.min) then return "rating:" .. tostring(math.floor(marker.min)) end
  return "none"
end

--- Does this photo carry the marker? Reads its colour label and rating from the catalog.
function Markers.isAccepted(marker, photo)
  if type(marker) ~= "table" then return false end
  if marker.kind == "label" then
    local ok, label = pcall(photo.getRawMetadata, photo, "colorNameForLabel")
    return ok and label == marker.value
  end
  if marker.kind == "rating" then
    local ok, rating = pcall(photo.getRawMetadata, photo, "rating")
    return ok and type(rating) == "number" and rating >= marker.min
  end
  return false
end

--- Catalog uuids of the registered photos that carry the marker (in registration order).
function Markers.acceptedUuids(marker, uuids, photosByUuid)
  local out = {}
  for _, uuid in ipairs(uuids) do
    local photo = photosByUuid[uuid]
    if photo and Markers.isAccepted(marker, photo) then out[#out + 1] = uuid end
  end
  return out
end

return Markers
