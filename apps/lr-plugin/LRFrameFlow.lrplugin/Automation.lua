--[[ LrInitPlugin: starts the automation channel when bridge.json says "automation": true.

Off by default. When on, the plugin asks the Bridge every two seconds for a test command
(GET /v1/automation/next), runs it with AutomationCommands and posts the result back.
AutomationStop.lua (LrShutdownPlugin) ends the loop on reload or quit. ]]

local LrApplication = import "LrApplication"
local LrTasks = import "LrTasks"

local AutomationCommands = require "AutomationCommands"
local AutomationState = require "AutomationState"
local BridgeClient = require "BridgeClient"
local Log = require "Log"

_G.LRFF_AUTOMATION_STOP = false

LrTasks.startAsyncTask(function()
  local cfg = BridgeClient.loadConfig()
  if not cfg or cfg.automation ~= true then return end
  AutomationState.enabled = true
  Log.info("automation channel on")
  while not _G.LRFF_AUTOMATION_STOP do
    local command, err = BridgeClient.automationNext()
    if command == BridgeClient.NO_CONTENT then
      LrTasks.sleep(2)
    elseif command then
      Log.info("automation: %s #%s", tostring(command.command), tostring(command.id))
      local ok, result = AutomationCommands.run(LrApplication.activeCatalog(), command)
      local _, postErr = BridgeClient.automationResult(command.id, ok, result)
      if postErr then Log.warn("automation: result not delivered: %s", postErr) end
    else
      Log.warn("automation: %s", tostring(err))
      LrTasks.sleep(5)
    end
  end
  AutomationState.enabled = false
  Log.info("automation channel off")
end)
