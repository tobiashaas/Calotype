--[[ LrInitPlugin: starts the automation channel when bridge.json says "automation": true.

Off by default. When on, the plugin asks the Bridge every two seconds for a test command
(GET /v1/automation/next), runs it with AutomationCommands and posts the result back.

Reload safety: Lightroom keeps the global table across "Reload Plug-in" and loads the new
plugin before unloading the old one, so a stop flag set on shutdown would also stop the new
loop. Instead every start takes a new generation number; a loop runs only while its number
is the current one, so the old loop ends by itself after a reload. ]]

local LrApplication = import "LrApplication"
local LrTasks = import "LrTasks"

local AutomationCommands = require "AutomationCommands"
local AutomationState = require "AutomationState"
local BridgeClient = require "BridgeClient"
local Log = require "Log"

_G.LRFF_AUTOMATION_GENERATION = (_G.LRFF_AUTOMATION_GENERATION or 0) + 1
local generation = _G.LRFF_AUTOMATION_GENERATION

local function current()
  return _G.LRFF_AUTOMATION_GENERATION == generation
end

LrTasks.startAsyncTask(function()
  local cfg = BridgeClient.loadConfig()
  if not cfg or cfg.automation ~= true then return end
  AutomationState.enabled = true
  Log.info("automation channel on (generation %d)", generation)
  local function step()
    local command, err = BridgeClient.automationNext()
    if not current() then return end -- a newer plugin took over while we were waiting
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
  while current() do
    -- One failing step must never end the channel (a yield error inside plain pcall once did).
    local ok, err = LrTasks.pcall(step)
    if not ok then
      Log.warn("automation step failed: %s", tostring(err))
      LrTasks.sleep(5)
    end
  end
  Log.info("automation channel of generation %d ended", generation)
end)
