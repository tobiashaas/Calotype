--[[ Library > Plug-in Extras > Apply profile to selected photos...

Predicted settings are written with photo:applyDevelopSettings in one catalog
transaction, so Lightroom's history and Edit > Undo work as usual. ]]

local LrApplication = import "LrApplication"
local LrBinding = import "LrBinding"
local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope = import "LrProgressScope"
local LrPrefs = import "LrPrefs"
local LrView = import "LrView"

local Actions = require "Actions"
local Retouch = require "Retouch"

local function askForProfile(context, items, count)
  local f = LrView.osFactory()
  local props = LrBinding.makePropertyTable(context)
  props.profileId = items[1].value
  local prefs = LrPrefs.prefsForPlugin()
  props.straighten = prefs.straighten == true
  for _, item in ipairs(Retouch.ITEMS) do props["retouch_" .. item.id] = prefs["retouch_" .. item.id] == true end
  local checks = {}
  for _, item in ipairs(Retouch.ITEMS) do
    checks[#checks + 1] = f:checkbox { value = LrView.bind("retouch_" .. item.id), title = item.title }
  end
  local answer = LrDialogs.presentModalDialog {
    title = LOC "$$$/LRFrameFlow/Apply/Title=LR-FrameFlow: Apply profile",
    contents = f:column {
      bind_to_object = props,
      spacing = f:control_spacing(),
      f:static_text { title = LOC("$$$/LRFrameFlow/Apply/Intro=Apply a profile to ^1 selected photos.", count) },
      f:popup_menu { value = LrView.bind "profileId", items = items, width_in_chars = 40 },
      f:checkbox {
        value = LrView.bind "straighten",
        title = LOC "$$$/LRFrameFlow/Apply/Straighten=Straighten photos with clear lines (your own crops stay)",
      },
      f:group_box {
        title = LOC "$$$/LRFrameFlow/Retouch/Box=Retouch with Lightroom AI masks",
        fill_horizontal = 1,
        f:row { checks[1], checks[2], checks[3] },
        f:row { checks[4], checks[5], checks[6] },
      },
    },
    actionVerb = LOC "$$$/LRFrameFlow/Apply/Action=Apply",
  }
  if answer ~= "ok" then return nil end
  prefs.straighten = props.straighten
  local retouch = {}
  for _, item in ipairs(Retouch.ITEMS) do
    prefs["retouch_" .. item.id] = props["retouch_" .. item.id]
    if props["retouch_" .. item.id] then retouch[#retouch + 1] = item.id end
  end
  for _, item in ipairs(items) do
    if item.value == props.profileId then
      return item.profile, { straighten = props.straighten, retouch = retouch }
    end
  end
  return nil
end

LrFunctionContext.postAsyncTaskWithContext("LRFrameFlow.apply", function(context)
  LrDialogs.attachErrorDialogToFunctionContext(context)
  local catalog = LrApplication.activeCatalog()

  local photos = catalog:getTargetPhotos()
  if #photos == 0 then
    LrDialogs.message(LOC "$$$/LRFrameFlow/Apply/NoSelection=Select the photos you want to edit first.", nil, "info")
    return
  end

  local items, err = Actions.readyProfiles()
  if not items then
    LrDialogs.message("LR-FrameFlow", err, "critical")
    return
  end
  if #items == 0 then
    LrDialogs.message(LOC "$$$/LRFrameFlow/Apply/NoProfileTitle=No profile is ready yet",
      LOC "$$$/LRFrameFlow/Apply/NoProfile=Train one first with \"Train profile from selected photos...\".", "info")
    return
  end

  local profile, options = askForProfile(context, items, #photos)
  if not profile then return end

  local progress = LrProgressScope {
    title = LOC("$$$/LRFrameFlow/Apply/Progress=LR-FrameFlow: applying \"^1\"", profile.name),
    functionContext = context,
  }
  local result = Actions.apply(catalog, photos, profile, progress, options)
  progress:done()
  if not result.canceled or result.title ~= "LR-FrameFlow" then
    LrDialogs.message(result.title, result.text, result.level)
  end
end)
