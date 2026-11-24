--[[ Library > Plug-in Extras > Manage profiles...

Rename or delete a profile. A deleted profile disappears from Calotype's lists (apply, keep
training); the server keeps its data, so nothing in the catalog changes. ]]

local LrBinding = import "LrBinding"
local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrView = import "LrView"

local Actions = require "Actions"
local BridgeClient = require "BridgeClient"

local function nameOf(items, id)
  for _, item in ipairs(items) do
    if item.value == id then return item.profile.name end
  end
  return ""
end

LrFunctionContext.postAsyncTaskWithContext("Calotype.manageProfiles", function(context)
  LrDialogs.attachErrorDialogToFunctionContext(context)

  local _, err = BridgeClient.health()
  if err then
    LrDialogs.message("Calotype", err, "critical")
    return
  end
  local items, listErr = Actions.allProfiles()
  if not items then
    LrDialogs.message("Calotype", listErr, "critical")
    return
  end
  if #items == 0 then
    LrDialogs.message(LOC "$$$/Calotype/Manage/NoneTitle=No profiles yet",
      LOC "$$$/Calotype/Manage/None=Train a profile from your edited photos first.", "info")
    return
  end

  local f = LrView.osFactory()
  local share = LrView.share
  local props = LrBinding.makePropertyTable(context)
  props.profileId = items[1].value
  props.name = items[1].profile.name
  props:addObserver("profileId", function(_, _, value) props.name = nameOf(items, value) end)

  local answer = LrDialogs.presentModalDialog {
    title = LOC "$$$/Calotype/Manage/Title=Calotype: Manage profiles",
    contents = f:column {
      bind_to_object = props,
      spacing = f:control_spacing(),
      f:row {
        f:static_text { title = LOC "$$$/Calotype/Train/Target=Profile:", alignment = "right", width = share "label" },
        f:popup_menu { value = LrView.bind "profileId", items = items, width_in_chars = 40 },
      },
      f:row {
        f:static_text { title = LOC "$$$/Calotype/Manage/NewName=Name:", alignment = "right", width = share "label" },
        f:edit_field { value = LrView.bind "name", width_in_chars = 30, immediate = true },
      },
      f:static_text {
        title = LOC "$$$/Calotype/Manage/Hint=Deleting removes the profile from Calotype's lists. Your photos stay as they are.",
        width_in_chars = 52, height_in_lines = 2,
      },
    },
    actionVerb = LOC "$$$/Calotype/Manage/Rename=Rename",
    otherVerb = LOC "$$$/Calotype/Manage/Delete=Delete …",
  }

  local oldName = nameOf(items, props.profileId)
  if answer == "ok" then
    local _, renameErr = Actions.renameProfile(props.profileId, props.name)
    if renameErr then
      LrDialogs.message("Calotype", renameErr, "warning")
    end
  elseif answer == "other" then
    local sure = LrDialogs.confirm(
      LOC("$$$/Calotype/Manage/ConfirmTitle=Delete the profile \"^1\"?", oldName),
      LOC "$$$/Calotype/Manage/Confirm=It can no longer be applied or trained.",
      LOC "$$$/Calotype/Manage/DeleteAction=Delete")
    if sure ~= "ok" then return end
    local _, deleteErr = Actions.deleteProfile(props.profileId)
    if deleteErr then
      LrDialogs.message("Calotype", deleteErr, "critical")
    end
  end
end)
