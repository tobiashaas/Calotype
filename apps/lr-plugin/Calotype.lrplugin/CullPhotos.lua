--[[ Library > Plug-in Extras > Sort selected photos (culling)...

Keep / check / sort out as collections under "Calotype"; stars, flags and labels are not
touched. Photos among the selection that already have stars or a pick/reject flag teach
Calotype the photographer's taste. ]]

local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope = import "LrProgressScope"

local Actions = require "Actions"

LrFunctionContext.postAsyncTaskWithContext("Calotype.cull", function(context)
  LrDialogs.attachErrorDialogToFunctionContext(context)
  local catalog = LrApplication.activeCatalog()
  local photos = catalog:getTargetPhotos()
  if #photos < 2 then
    LrDialogs.message(LOC "$$$/Calotype/Cull/NoSelection=Select the photos of a shoot first.", nil, "info")
    return
  end
  local progress = LrProgressScope {
    title = LOC("$$$/Calotype/Cull/Progress=Calotype: sorting ^1 photos", #photos),
    functionContext = context,
  }
  local result = Actions.cull(catalog, photos, progress)
  progress:done()
  if not result.canceled or result.title ~= "Calotype" then
    LrDialogs.message(result.title, result.text, result.level)
  end
end)
