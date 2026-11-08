--[[ Library > Plug-in Extras > Sort selected photos (culling)...

Keep / check / sort out as collections under "Tarsier"; stars, flags and labels are not
touched. Photos among the selection that already have stars or a pick/reject flag teach
Tarsier the photographer's taste. ]]

local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope = import "LrProgressScope"

local Actions = require "Actions"

LrFunctionContext.postAsyncTaskWithContext("Tarsier.cull", function(context)
  LrDialogs.attachErrorDialogToFunctionContext(context)
  local catalog = LrApplication.activeCatalog()
  local photos = catalog:getTargetPhotos()
  if #photos < 2 then
    LrDialogs.message(LOC "$$$/Tarsier/Cull/NoSelection=Select the photos of a shoot first.", nil, "info")
    return
  end
  local progress = LrProgressScope {
    title = LOC("$$$/Tarsier/Cull/Progress=Tarsier: sorting ^1 photos", #photos),
    functionContext = context,
  }
  local result = Actions.cull(catalog, photos, progress)
  progress:done()
  if not result.canceled or result.title ~= "Tarsier" then
    LrDialogs.message(result.title, result.text, result.level)
  end
end)
