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
local Fresh = require "Fresh"
local LookPresets = require "LookPresets"
local Retouch = require "Retouch"

local OWN_EDITS = "own-edits"

local function askForProfile(context, items, count)
  local f = LrView.osFactory()
  local props = LrBinding.makePropertyTable(context)
  local prefs = LrPrefs.prefsForPlugin()
  props.profileId = items[1].value
  for _, item in ipairs(items) do
    if item.value == prefs.lastProfileId then props.profileId = item.value end
  end
  local looks = { { title = LOC "$$$/Calotype/Look/FromProfile=From the profile / your edited photos", value = "" } }
  for _, item in ipairs(LookPresets.items()) do looks[#looks + 1] = item end
  props.look = ""
  for _, item in ipairs(looks) do
    if item.value == prefs.lastLook then props.look = item.value end
  end
  props.straighten = prefs.straighten == true
  props.learnFromEdits = prefs.learnFromEdits == true
  props.consistentSeries = prefs.consistentSeries == true
  props.fresh = prefs.fresh == true
  for _, item in ipairs(Retouch.ITEMS) do props["retouch_" .. item.id] = prefs["retouch_" .. item.id] == true end
  local checks = {}
  for _, item in ipairs(Retouch.ITEMS) do
    checks[#checks + 1] = f:checkbox { value = LrView.bind("retouch_" .. item.id), title = item.title }
  end
  local answer = LrDialogs.presentModalDialog {
    title = LOC "$$$/Calotype/Apply/Title=Calotype: Apply profile",
    contents = f:column {
      bind_to_object = props,
      spacing = f:control_spacing(),
      f:static_text { title = LOC("$$$/Calotype/Apply/Intro=Apply a profile to ^1 selected photos.", count) },
      f:popup_menu { value = LrView.bind "profileId", items = items, width_in_chars = 40 },
      f:row {
        f:static_text { title = LOC "$$$/Calotype/Look/Label=Look:" },
        f:popup_menu { value = LrView.bind "look", items = looks, width_in_chars = 36 },
      },
      f:static_text {
        title = LOC "$$$/Calotype/Look/Hint=One of your presets: its look (curve, colors, grain …), exposure and white balance per photo from Calotype.",
        width_in_chars = 52, height_in_lines = 2,
      },
      f:checkbox {
        value = LrView.bind "straighten",
        title = LOC "$$$/Calotype/Apply/Straighten=Straighten photos with clear lines (your own crops stay)",
      },
      f:checkbox {
        value = LrView.bind "fresh",
        title = LOC "$$$/Calotype/Fresh/Option=Start from zero: reset all selected photos first",
        enabled = LrBinding.keyIsNot("profileId", OWN_EDITS),
      },
      f:static_text {
        title = LOC "$$$/Calotype/Fresh/Hint=Replaces existing edits, crops and masks, so only the profile and the look remain. Needs a trained profile. The state before is kept as a snapshot.",
        width_in_chars = 52, height_in_lines = 3,
      },
      f:checkbox {
        value = LrView.bind "learnFromEdits",
        title = LOC "$$$/Calotype/Apply/LearnFromEdits=Learn this shoot's look from the photos in the selection you already edited",
        enabled = LrBinding.keyIsNot("profileId", OWN_EDITS),
      },
      f:static_text {
        title = LOC "$$$/Calotype/Apply/LearnFromEditsHint=Edit about 20 typical photos first; they stay as they are.",
      },
      f:checkbox {
        value = LrView.bind "consistentSeries",
        title = LOC "$$$/Calotype/Apply/ConsistentSeries=Keep series consistent: same exposure and white balance within a scene",
      },
      f:static_text {
        title = LOC "$$$/Calotype/Apply/ConsistentSeriesHint=Photos taken shortly after one another of the same scene. Your edited photos stay as they are.",
        width_in_chars = 52, height_in_lines = 2,
      },
      f:group_box {
        title = LOC "$$$/Calotype/Retouch/Box=Retouch with Lightroom AI masks",
        fill_horizontal = 1,
        f:row { checks[1], checks[2], checks[3] },
        f:row { checks[4], checks[5], checks[6] },
      },
    },
    actionVerb = LOC "$$$/Calotype/Apply/Action=Apply",
  }
  if answer ~= "ok" then return nil end
  prefs.straighten = props.straighten
  prefs.lastProfileId = props.profileId
  prefs.learnFromEdits = props.learnFromEdits
  prefs.consistentSeries = props.consistentSeries
  prefs.fresh = props.fresh
  prefs.lastLook = props.look
  local look = LookPresets.settings(props.look)
  local retouch = {}
  for _, item in ipairs(Retouch.ITEMS) do
    prefs["retouch_" .. item.id] = props["retouch_" .. item.id]
    if props["retouch_" .. item.id] then retouch[#retouch + 1] = item.id end
  end
  for _, item in ipairs(items) do
    if item.value == props.profileId then
      -- Start from zero leaves no edited photo to learn from; the two exclude each other.
      local fresh = props.fresh == true and item.value ~= OWN_EDITS
      return item.profile, { straighten = props.straighten, retouch = retouch, fresh = fresh,
        consistentSeries = props.consistentSeries == true,
        learnFromEdits = not fresh and (props.learnFromEdits or item.value == OWN_EDITS), look = look }
    end
  end
  return nil
end

LrFunctionContext.postAsyncTaskWithContext("Calotype.apply", function(context)
  LrDialogs.attachErrorDialogToFunctionContext(context)
  local catalog = LrApplication.activeCatalog()

  local photos = catalog:getTargetPhotos()
  if #photos == 0 then
    LrDialogs.message(LOC "$$$/Calotype/Apply/NoSelection=Select the photos you want to edit first.", nil, "info")
    return
  end

  local items, err = Actions.readyProfiles()
  if not items then
    LrDialogs.message("Calotype", err, "critical")
    return
  end
  -- Always offered, also without any trained profile: the look of the photos already edited.
  items[#items + 1] = {
    title = LOC "$$$/Calotype/Apply/OwnEditsItem=No profile: only from the photos I already edited",
    value = OWN_EDITS,
    profile = Actions.ownEditsProfile(photos),
  }

  local profile, options = askForProfile(context, items, #photos)
  if not profile then return end
  if options.fresh then
    local go = LrDialogs.confirm(
      LOC("$$$/Calotype/Fresh/ConfirmTitle=Reset ^1 photos and edit them from zero?", #photos),
      LOC("$$$/Calotype/Fresh/Confirm=Existing edits, crops and masks of all selected photos are replaced. The state before is kept on every photo as the snapshot \"^1\".", Fresh.snapshotName()),
      LOC "$$$/Calotype/Fresh/ConfirmAction=Reset and edit")
    if go ~= "ok" then return end
  end

  local progress = LrProgressScope {
    title = LOC("$$$/Calotype/Apply/Progress=Calotype: applying \"^1\"", profile.name),
    functionContext = context,
  }
  local result = Actions.apply(catalog, photos, profile, progress, options)
  progress:done()
  if not result.canceled or result.title ~= "Calotype" then
    LrDialogs.message(result.title, result.text, result.level)
  end
end)
