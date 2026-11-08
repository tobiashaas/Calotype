--[[ Library > Plug-in Extras > Sort selected photos (culling)...

Keep / check / sort out as collections under "LR-FrameFlow"; stars, flags and labels are not
touched. Photos among the selection that already have stars or a pick/reject flag teach
LR-FrameFlow the photographer's taste. ]]

local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope = import "LrProgressScope"

local Actions = require "Actions"

LrFunctionContext.postAsyncTaskWithContext("LRFrameFlow.cull", function(context)
  LrDialogs.attachErrorDialogToFunctionContext(context)
  local catalog = LrApplication.activeCatalog()
  local photos = catalog:getTargetPhotos()
  if #photos < 2 then
    LrDialogs.message(LOC "$$$/LRFrameFlow/Cull/NoSelection=Select the photos of a shoot first.", nil, "info")
    return
  end
  local progress = LrProgressScope {
    title = LOC("$$$/LRFrameFlow/Cull/Progress=LR-FrameFlow: sorting ^1 photos", #photos),
    functionContext = context,
  }
  local result = Actions.cull(catalog, photos, progress)
  progress:done()
  if not result.canceled or result.title ~= "LR-FrameFlow" then
    LrDialogs.message(result.title, result.text, result.level)
  end
end)
